from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

import aiosqlite
from fastapi import FastAPI

SCHEMA = """
CREATE TABLE IF NOT EXISTS worries (
    id TEXT PRIMARY KEY,
    status TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS watchers (
    id TEXT PRIMARY KEY,
    worry_id TEXT NOT NULL,
    state TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS peers (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS sharing_rules (
    peer_id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS questions_log (
    id TEXT PRIMARY KEY,
    asked_at TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS schedule (
    watcher_id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS pairings (
    mailbox_id TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS activity_samples (
    ts TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS me (
    key TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS relay_state (
    key TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS seen_nonces (
    nonce TEXT PRIMARY KEY,
    ts TEXT NOT NULL,
    data TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS push_subscriptions (
    endpoint TEXT PRIMARY KEY,
    data TEXT NOT NULL
);
"""


class JsonStore:
    """A table of {key_column PRIMARY KEY, ...index_columns, data JSON}.

    Table/column names below are always literals from this module's own call
    sites, never request-derived, so the f-string SQL carries no injection risk;
    values are always passed as bound parameters.
    """

    def __init__(
        self,
        conn: aiosqlite.Connection,
        table: str,
        key_column: str,
        index_columns: tuple[str, ...] = (),
    ) -> None:
        self._conn = conn
        self._table = table
        self._key_column = key_column
        self._index_columns = index_columns

    async def put(self, key: str, data: dict[str, Any], **index_values: str) -> None:
        columns = [self._key_column, *self._index_columns, "data"]
        values: list[str] = [
            key,
            *(index_values[c] for c in self._index_columns),
            json.dumps(data),
        ]
        placeholders = ", ".join("?" for _ in columns)
        updates = ", ".join(f"{c}=excluded.{c}" for c in columns if c != self._key_column)
        await self._conn.execute(
            f"INSERT INTO {self._table} ({', '.join(columns)}) VALUES ({placeholders}) "
            f"ON CONFLICT({self._key_column}) DO UPDATE SET {updates}",
            values,
        )
        await self._conn.commit()

    async def get(self, key: str) -> dict[str, Any] | None:
        cursor = await self._conn.execute(
            f"SELECT data FROM {self._table} WHERE {self._key_column} = ?", (key,)
        )
        row = await cursor.fetchone()
        return json.loads(row[0]) if row else None

    async def query(self, **filters: str) -> list[dict[str, Any]]:
        where, params = self._where(filters)
        cursor = await self._conn.execute(f"SELECT data FROM {self._table} {where}", params)
        rows = await cursor.fetchall()
        return [json.loads(row[0]) for row in rows]

    async def delete(self, key: str) -> None:
        await self._conn.execute(f"DELETE FROM {self._table} WHERE {self._key_column} = ?", (key,))
        await self._conn.commit()

    async def delete_below(self, column: str, cutoff: str) -> None:
        """Delete rows whose key/index `column` sorts below `cutoff` (ISO timestamps)."""
        if column not in (self._key_column, *self._index_columns):
            raise ValueError(f"{column} is not a column of {self._table}")
        await self._conn.execute(f"DELETE FROM {self._table} WHERE {column} < ?", (cutoff,))
        await self._conn.commit()

    async def count(self, **filters: str) -> int:
        where, params = self._where(filters)
        cursor = await self._conn.execute(f"SELECT COUNT(*) FROM {self._table} {where}", params)
        row = await cursor.fetchone()
        return int(row[0]) if row else 0

    @staticmethod
    def _where(filters: dict[str, str]) -> tuple[str, list[str]]:
        if not filters:
            return "", []
        return "WHERE " + " AND ".join(f"{c} = ?" for c in filters), list(filters.values())


class Store:
    def __init__(self, conn: aiosqlite.Connection) -> None:
        self.worries = JsonStore(conn, "worries", "id", ("status",))
        self.watchers = JsonStore(conn, "watchers", "id", ("worry_id", "state"))
        self.peers = JsonStore(conn, "peers", "id")
        self.sharing_rules = JsonStore(conn, "sharing_rules", "peer_id")
        self.questions_log = JsonStore(conn, "questions_log", "id", ("asked_at",))
        self.push_subscriptions = JsonStore(conn, "push_subscriptions", "endpoint")
        # Reassurance-internal (T-14/T-15), not contracts: pending pairings (derived key +
        # expiry, never the code), activity samples, my help/check-in state, the relay cursor,
        # and query nonces already answered (replay guard).
        self.pairings = JsonStore(conn, "pairings", "mailbox_id")
        self.activity_samples = JsonStore(conn, "activity_samples", "ts")
        self.me = JsonStore(conn, "me", "key")
        self.relay_state = JsonStore(conn, "relay_state", "key")
        self.seen_nonces = JsonStore(conn, "seen_nonces", "nonce", ("ts",))
        # Scheduler-internal (T-10), not a contract: {next_run_at, consecutive_errors}.
        self.schedule = JsonStore(conn, "schedule", "watcher_id")
        # Held around every read-modify-write of a worry/watcher pair, by the routes and the
        # scheduler alike, so a let-go can't interleave with a scheduler run (and vice versa).
        self.write_lock = asyncio.Lock()

    async def sandboxes_live(self) -> int:
        # A paused watcher keeps its sandbox (T-10), so it still counts as live.
        return await self.watchers.count(state="active") + await self.watchers.count(state="paused")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    db_path = os.environ.get("WARDEN_DB_PATH", "warden.db")
    async with aiosqlite.connect(db_path) as conn:
        await conn.executescript(SCHEMA)
        await conn.commit()
        app.state.store = Store(conn)
        yield
