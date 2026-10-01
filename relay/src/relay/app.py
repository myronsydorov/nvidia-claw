"""The relay: a dumb mailbox that stores and forwards ciphertext (CONTRACTS §2, ADR-0004).

It never sees plain text. Each message is `{ciphertext, sender_key_id}` addressed to a
recipient key id; the ciphertext is stored as raw bytes, and logs carry a key-id prefix and
a size only. Messages expire after 24 h and each mailbox keeps at most 200.

Honest limit (THREAT_MODEL A6): there is no mailbox auth. Anyone who knows a key id can
read that mailbox's ciphertext. Key ids are hashes of public keys, which only ever travel
encrypted (pairing), and everything in a mailbox is end-to-end encrypted.
"""

import asyncio
import base64
import binascii
import logging
import os
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from typing import Annotated

import aiosqlite
from fastapi import FastAPI, HTTPException, Path, Query, Request, Response, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

log = logging.getLogger("relay")

KEY_ID_PATTERN = r"^[0-9a-f]{32}$"
MAX_CIPHERTEXT_BYTES = 4096
MAX_PER_MAILBOX = 200
MAX_TOTAL_MESSAGES = 50_000  # global disk bound: 50k × 4 KiB ≈ 200 MB worst case
MAX_BODY_BYTES = 16 * 1024  # checked from Content-Length before the body is read
TTL = timedelta(hours=24)

SCHEMA = """
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    recipient TEXT NOT NULL,
    sender TEXT NOT NULL,
    ciphertext BLOB NOT NULL,
    ts TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_recipient ON messages (recipient, id);
"""

KeyId = Annotated[str, Path(pattern=KEY_ID_PATTERN)]


class PostMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # A loose string bound so the body stays small; the exact 4 KiB decoded cap is checked in
    # `_decode` and answers 413 (CONTRACTS §2).
    ciphertext: str = Field(min_length=1, max_length=4 * MAX_CIPHERTEXT_BYTES)
    sender_key_id: str = Field(pattern=KEY_ID_PATTERN)


class Posted(BaseModel):
    id: int


class MailboxMessage(BaseModel):
    id: int
    ciphertext: str
    sender_key_id: str
    ts: datetime


class HealthResponse(BaseModel):
    status: str


def _decode(ciphertext: str) -> bytes:
    try:
        raw = base64.b64decode(ciphertext, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "ciphertext is not base64"
        ) from exc
    if len(raw) > MAX_CIPHERTEXT_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "ciphertext too large")
    return raw


def create_app(db_path: str | None = None) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        path = db_path or os.environ.get("RELAY_DB_PATH", "relay.db")
        async with aiosqlite.connect(path) as conn:
            await conn.executescript(SCHEMA)
            await conn.commit()
            app.state.conn = conn
            app.state.lock = asyncio.Lock()
            yield

    app = FastAPI(
        title="Custody relay", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None
    )

    @app.middleware("http")
    async def limit_body(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.method == "POST":
            length = request.headers.get("content-length")
            if length is None or not length.isdigit():
                return JSONResponse({"detail": "content-length required"}, status_code=411)
            if int(length) > MAX_BODY_BYTES:
                return JSONResponse({"detail": "body too large"}, status_code=413)
        return await call_next(request)

    def _conn(request: Request) -> aiosqlite.Connection:
        conn: aiosqlite.Connection = request.app.state.conn
        return conn

    @app.get("/v1/health")
    async def health() -> HealthResponse:
        return HealthResponse(status="ok")

    @app.post("/v1/mailbox/{recipient_key_id}", status_code=status.HTTP_202_ACCEPTED)
    async def post_message(recipient_key_id: KeyId, body: PostMessage, request: Request) -> Posted:
        raw = _decode(body.ciphertext)
        now = datetime.now(UTC)
        conn = _conn(request)
        lock: asyncio.Lock = request.app.state.lock
        async with lock:
            await conn.execute("DELETE FROM messages WHERE ts < ?", ((now - TTL).isoformat(),))
            total_cursor = await conn.execute("SELECT COUNT(*) FROM messages")
            total = await total_cursor.fetchone()
            if total is not None and int(total[0]) >= MAX_TOTAL_MESSAGES:
                await conn.commit()
                log.warning("relay full; refusing new messages")
                raise HTTPException(status.HTTP_507_INSUFFICIENT_STORAGE, "relay full")
            cursor = await conn.execute(
                "INSERT INTO messages (recipient, sender, ciphertext, ts) VALUES (?, ?, ?, ?)",
                (recipient_key_id, body.sender_key_id, raw, now.isoformat()),
            )
            message_id = cursor.lastrowid
            # Cap each mailbox: the oldest messages beyond MAX_PER_MAILBOX are dropped.
            await conn.execute(
                "DELETE FROM messages WHERE recipient = ? AND id NOT IN "
                "(SELECT id FROM messages WHERE recipient = ? ORDER BY id DESC LIMIT ?)",
                (recipient_key_id, recipient_key_id, MAX_PER_MAILBOX),
            )
            await conn.commit()
        assert message_id is not None
        log.info("posted to=%s… bytes=%d", recipient_key_id[:6], len(raw))
        return Posted(id=message_id)

    @app.get("/v1/mailbox/{my_key_id}")
    async def get_messages(
        my_key_id: KeyId,
        request: Request,
        since: Annotated[int, Query(ge=0, le=2**62)] = 0,
    ) -> list[MailboxMessage]:
        cutoff = (datetime.now(UTC) - TTL).isoformat()
        cursor = await _conn(request).execute(
            "SELECT id, ciphertext, sender, ts FROM messages "
            "WHERE recipient = ? AND id > ? AND ts >= ? ORDER BY id LIMIT ?",
            (my_key_id, since, cutoff, MAX_PER_MAILBOX),
        )
        rows = await cursor.fetchall()
        return [
            MailboxMessage(
                id=int(row[0]),
                ciphertext=base64.b64encode(bytes(row[1])).decode("ascii"),
                sender_key_id=str(row[2]),
                ts=datetime.fromisoformat(str(row[3])),
            )
            for row in rows
        ]

    return app


app = create_app()
