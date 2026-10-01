"""In-process L2 harness: one real relay app (ASGI transport, its own SQLite file) and two
Reassurance services with their own stores and keys. No sockets, no sleeps. The fixtures are
registered in conftest.py.
"""

import asyncio
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
import httpx2 as httpx
import pytest
from nacl.public import PrivateKey
from relay.app import create_app
from warden.db import SCHEMA, Store
from warden.events import EventBus
from warden.models import AskPeerResponse
from warden.reassurance.relay_client import RelayClient
from warden.reassurance.service import Reassurance
from warden.reassurance.signal import SignalInputs
from warden.reassurance.sources import NoProbe

NOW = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


@dataclass
class Side:
    service: Reassurance
    store: Store
    key: PrivateKey


@dataclass
class Pair:
    alice: Side
    bob: Side
    relay_db: str
    clock: Clock
    posts: list[str]  # recipient key ids of every relay POST, in order

    async def pair(self) -> tuple[str, str]:
        """Alice starts, Bob joins, Alice's poller completes. → (alice's id for bob, bob's id
        for alice)."""
        started = await self.alice.service.start_pairing("Bob")
        bob_view = await self.bob.service.join_pairing(started.code, "Alice")
        await self.alice.service.poll_once()
        [row] = await self.alice.store.peers.query()
        return row["peer"]["id"], bob_view.id

    async def alice_asks(self, peer_id: str, q: str = "ok") -> AskPeerResponse:
        """Alice asks while Bob's poller runs (in the app, that's Bob's background task)."""
        task = asyncio.create_task(self.alice.service.ask(peer_id, q))  # type: ignore[arg-type]
        while not task.done():
            await self.bob.service.poll_once()
            await asyncio.sleep(0.01)
        return task.result()


def signal_returning(
    answer: dict[str, Any] | None = None,
) -> Callable[[datetime, SignalInputs], object]:
    def fn(now: datetime, inputs: SignalInputs) -> object:
        return (
            answer
            if answer is not None
            else {"level": "normal", "reason": "active_as_usual", "ts": now}
        )

    return fn


@pytest.fixture
def fast_pairing_kdf(monkeypatch: pytest.MonkeyPatch) -> None:
    """Argon2id at its minimum cost so pairing tests stay fast; test_crypto checks the real
    parameters, and the end-to-end test runs them."""
    from nacl.pwhash import argon2id
    from warden.reassurance import crypto

    def cheap(code: str) -> tuple[str, bytes]:
        material = argon2id.kdf(
            48,
            code.encode("ascii"),
            crypto.PAIRING_SALT,
            opslimit=argon2id.OPSLIMIT_MIN,
            memlimit=argon2id.MEMLIMIT_MIN,
        )
        return material[:16].hex(), material[16:]

    monkeypatch.setattr(crypto, "derive_pairing", cheap)


@pytest.fixture
async def pair(tmp_path: Path, fast_pairing_kdf: None) -> AsyncIterator[Pair]:
    relay_db = str(tmp_path / "relay.db")
    relay_app = create_app(relay_db)
    clock = Clock()
    posts: list[str] = []

    async def record(request: httpx.Request) -> None:
        if request.method == "POST":
            posts.append(request.url.path.rsplit("/", 1)[-1])

    async with relay_app.router.lifespan_context(relay_app):
        transport = httpx.ASGITransport(app=relay_app)
        async with (
            aiosqlite.connect(tmp_path / "a.db") as conn_a,
            aiosqlite.connect(tmp_path / "b.db") as conn_b,
        ):
            sides = []
            for conn in (conn_a, conn_b):
                await conn.executescript(SCHEMA)
                store = Store(conn)
                key = PrivateKey.generate()
                relay = RelayClient("http://relay", transport=transport)
                relay._client.event_hooks["request"].append(record)
                service = Reassurance(
                    store,
                    EventBus(),
                    key,
                    relay,
                    NoProbe(),
                    now=clock,
                    signal_fn=signal_returning(),
                    busy_fn=lambda now: False,
                    ask_timeout_s=2.0,
                    ask_poll_s=0.01,
                )
                sides.append(Side(service, store, key))
            yield Pair(sides[0], sides[1], relay_db, clock, posts)
