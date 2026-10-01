"""Pre-populate a test's SQLite file with rows the API itself can't create yet
(e.g. a Watcher — that's T-09's compiler). Uses a plain sync sqlite3 connection,
closed before the app's own aiosqlite connection opens the same file, so the two
never share an event loop.
"""

import json
import sqlite3
from typing import Any

from warden.db import SCHEMA


def _insert(
    db_path: str, table: str, key_column: str, key: str, data: dict[str, Any], **index: str
) -> None:
    conn = sqlite3.connect(db_path)
    try:
        conn.executescript(SCHEMA)
        columns = [key_column, *index.keys(), "data"]
        placeholders = ", ".join("?" for _ in columns)
        values = [key, *index.values(), json.dumps(data)]
        conn.execute(f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})", values)
        conn.commit()
    finally:
        conn.close()


def seed_worry(db_path: str, worry: dict[str, Any], timeline: list[dict[str, Any]]) -> None:
    _insert(
        db_path,
        "worries",
        "id",
        worry["id"],
        {"worry": worry, "timeline": timeline},
        status=worry["status"],
    )


def seed_watcher(db_path: str, watcher: dict[str, Any]) -> None:
    _insert(
        db_path,
        "watchers",
        "id",
        watcher["id"],
        watcher,
        worry_id=watcher["worry_id"],
        state=watcher["state"],
    )


def seed_peer(db_path: str, peer: dict[str, Any]) -> None:
    _insert(
        db_path,
        "peers",
        "id",
        peer["id"],
        {
            "peer": peer,
            "last_answer": None,
            "last_answer_at": None,
            "last_asked_at": None,
            "pair_nonce": "00" * 16,
        },
    )
