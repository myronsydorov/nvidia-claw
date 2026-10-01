"""Acceptance for T-14 + T-15: a real relay and two real Wardens, each its own uvicorn process
on its own port with its own SQLite database and key file, pair with a one-time code and
answer "ok?" end to end. Then the relay's database is dumped and searched for plain text.

Nothing is mocked except the sandbox driver (irrelevant to L2) and the activity probe (off,
so the answer doesn't depend on this machine's idle time).
"""

import base64
import os
import socket
import sqlite3
import subprocess
import sys
import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import httpx2 as httpx
import pytest
from nacl.public import PrivateKey, PublicKey
from warden.reassurance import crypto
from warden.reassurance.keys import key_id
from warden.reassurance.relay_client import envelope_body

TOKEN_A = "token-alice"
TOKEN_B = "token-anna"


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


@dataclass
class Proc:
    url: str
    process: subprocess.Popen[bytes]
    log: Path


def _start(module: str, env: dict[str, str], log: Path, health: str, token: str | None) -> Proc:
    port = _free_port()
    full_env = {k: v for k, v in os.environ.items() if not k.startswith(("WARDEN_", "RELAY_"))}
    full_env.update(env)
    out = log.open("wb")
    process = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", module, "--host", "127.0.0.1", "--port", str(port)],
        env=full_env,
        stdout=out,
        stderr=subprocess.STDOUT,
    )
    url = f"http://127.0.0.1:{port}"
    headers = {"Authorization": f"Bearer {token}"} if token else {}
    deadline = time.monotonic() + 20
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError(f"{module} exited:\n{log.read_text()}")
        try:
            if httpx.get(url + health, headers=headers, timeout=1).status_code == 200:
                return Proc(url, process, log)
        except httpx.HTTPError:
            pass
        time.sleep(0.1)
    process.terminate()
    raise RuntimeError(f"{module} never became healthy:\n{log.read_text()}")


@dataclass
class World:
    relay: Proc
    alice: Proc
    anna: Proc
    relay_db: Path
    alice_key: Path
    anna_key: Path


@pytest.fixture
def world(tmp_path: Path) -> Iterator[World]:
    relay_db = tmp_path / "relay.db"
    relay = _start(
        "relay.app:app",
        {"RELAY_DB_PATH": str(relay_db)},
        tmp_path / "relay.log",
        "/v1/health",
        None,
    )
    procs = [relay]
    try:

        def warden(name: str, token: str) -> Proc:
            env = {
                "WARDEN_DB_PATH": str(tmp_path / f"{name}.db"),
                "WARDEN_KEY_PATH": str(tmp_path / f"{name}.key"),
                "WARDEN_DEVICE_TOKEN": token,
                "RELAY_URL": relay.url,
                "WARDEN_RELAY_POLL_S": "0.2",
                "WARDEN_ASK_TIMEOUT_S": "10",
                "WARDEN_ASK_COOLDOWN_S": "0",  # this test asks three times in a row
                "WARDEN_SCHEDULER": "off",
                "WARDEN_COMPILER": "off",
                "CUSTODY_SANDBOX": "mock",
                "CUSTODY_ACTIVITY": "off",
            }
            proc = _start("warden.app:app", env, tmp_path / f"{name}.log", "/api/health", token)
            procs.append(proc)
            return proc

        alice = warden("alice", TOKEN_A)
        anna = warden("anna", TOKEN_B)
        yield World(relay, alice, anna, relay_db, tmp_path / "alice.key", tmp_path / "anna.key")
    finally:
        for proc in procs:
            proc.process.terminate()
            proc.process.wait(timeout=10)


def _client(proc: Proc, token: str) -> httpx.Client:
    return httpx.Client(base_url=proc.url, headers={"Authorization": f"Bearer {token}"}, timeout=30)


def _wait_for_peer(client: httpx.Client) -> dict[str, object]:
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        people = client.get("/api/people").json()
        if people:
            return dict(people[0]["peer"])
        time.sleep(0.1)
    raise AssertionError("pairing never completed on the offering side")


def test_two_wardens_pair_and_answer_ok_through_the_relay(world: World) -> None:
    alice = _client(world.alice, TOKEN_A)
    anna = _client(world.anna, TOKEN_B)

    # --- T-14: pairing with a one-time code, through the relay ----------------------------
    started = alice.post("/api/pairing", json={"display_name": "Anna"})
    assert started.status_code == 200, started.text
    code = started.json()["code"]
    joined = anna.post("/api/pairing/join", json={"code": code, "display_name": "Alice"})
    assert joined.status_code == 200, joined.text
    anna_id_for_alice = joined.json()["id"]
    alice_peer = _wait_for_peer(alice)
    alice_id_for_anna = str(alice_peer["id"])
    assert alice_peer["display_name"] == "Anna"
    # Both screens show the same fingerprint, and the code-showing side learns it's done.
    status = alice.get(f"/api/pairing/{started.json()['pairing_id']}").json()
    assert status["state"] == "paired"
    assert status["peer"]["fingerprint"] == joined.json()["fingerprint"]
    assert alice_peer["fingerprint"] == joined.json()["fingerprint"]
    # Both tap "It matches"; until then neither side's sharing rule is active.
    assert alice.post(f"/api/people/{alice_id_for_anna}/confirm").status_code == 204
    assert anna.post(f"/api/people/{anna_id_for_alice}/confirm").status_code == 204
    # Joining again with the same code is refused: Anna is already paired with Alice.
    rejoin = anna.post("/api/pairing/join", json={"code": code, "display_name": "x"})
    assert rejoin.status_code == 409

    # --- T-15: "Is Anna OK?" ---------------------------------------------------------------
    assert anna.post("/api/me/check-in").status_code == 204
    asked = alice.post(f"/api/people/{alice_id_for_anna}/ask", json={"q": "ok"})
    assert asked.status_code == 200, asked.text
    body = asked.json()
    assert (body["answer"]["level"], body["answer"]["reason"]) == ("normal", "active_as_usual")
    receipt = body["receipt"]
    assert receipt["fields_shared"] == ["level", "reason", "ts"]
    assert receipt["location_shared"] is False
    assert 0 < receipt["bytes_sent"] < 512

    # The receipt's bytes are exactly the answer's POST body, as stored on the relay.
    answer_msg_id = int(receipt["egress_log_ref"].removeprefix("relay:"))
    conn = sqlite3.connect(world.relay_db)
    ciphertext, sender = conn.execute(
        "SELECT ciphertext, sender FROM messages WHERE id = ?", (answer_msg_id,)
    ).fetchone()
    conn.close()
    assert receipt["bytes_sent"] == len(
        envelope_body(base64.b64encode(ciphertext).decode(), sender)
    )

    # Anna sees the question in her log; Alice sees the last answer.
    log = anna.get("/api/sharing-rules").json()["questions_log"]
    assert [(e["peer_id"], e["question"], e["answer_level"]) for e in log] == [
        (anna_id_for_alice, "ok", "normal")
    ]
    assert alice.get("/api/people").json()[0]["last_answer"]["level"] == "normal"
    assert anna.get("/api/ledger").json()["peer_questions_answered"] == 1

    # "I need help" flows through too.
    assert anna.post("/api/me/help").status_code == 204
    helped = alice.post(f"/api/people/{alice_id_for_anna}/ask", json={"q": "ok"}).json()
    assert (helped["answer"]["level"], helped["answer"]["reason"]) == ("help", "asked_for_help")

    # Anna revokes Alice: the next answer says nothing, and is still logged.
    rules = anna.get("/api/sharing-rules").json()
    rules["rules"][0]["active"] = False
    assert anna.put("/api/sharing-rules", json=rules).status_code == 200
    revoked = alice.post(f"/api/people/{alice_id_for_anna}/ask", json={"q": "ok"}).json()
    assert revoked["answer"]["level"] == "unknown"
    assert len(anna.get("/api/sharing-rules").json()["questions_log"]) == 3

    # --- T-14: the relay database contains no plain text ---------------------------------
    _assert_relay_holds_only_ciphertext(world, code)

    # No process logged the code, a display name or an answer.
    for proc in (world.relay, world.alice, world.anna):
        text = proc.log.read_text()
        for needle in (code, "Anna", "active_as_usual", "asked_for_help"):
            assert needle not in text, f"{needle!r} leaked into {proc.log.name}"


def _assert_relay_holds_only_ciphertext(world: World, code: str) -> None:
    alice_key = PrivateKey(world.alice_key.read_bytes())
    anna_key = PrivateKey(world.anna_key.read_bytes())
    pubkeys = [bytes(alice_key.public_key), bytes(anna_key.public_key)]

    conn = sqlite3.connect(world.relay_db)
    dump = "\n".join(conn.iterdump())
    rows = conn.execute("SELECT recipient, sender, ciphertext FROM messages ORDER BY id").fetchall()
    conn.close()
    raw_file = world.relay_db.read_bytes()
    for suffix in ("-wal", "-journal"):
        extra = Path(str(world.relay_db) + suffix)
        if extra.exists():
            raw_file += extra.read_bytes()

    # Offer, accept, and 3 query/answer round trips.
    assert len(rows) == 1 + 1 + 6

    forbidden_text = [
        "level", "reason", "normal", "active_as_usual", "asked_for_help", "not_enough_data",
        "help", "query", "answer", "pair_offer", "pair_accept", "public_key", "proof",
        "nonce", "Anna", "Alice", code,
    ]  # fmt: skip
    forbidden_bytes = [w.encode() for w in forbidden_text]
    for pk in pubkeys:
        forbidden_bytes += [pk, base64.b64encode(pk), pk.hex().encode()]
    for needle in forbidden_bytes:
        assert needle not in raw_file, f"plain text {needle!r} found in the relay database file"
        assert needle.decode("latin-1") not in dump, f"plain text {needle!r} in the SQL dump"

    # Only key ids are visible, and every stored blob really is a ciphertext the right key
    # opens (so the check above searched the real messages, not decoys).
    alice_id, anna_id = key_id(pubkeys[0]), key_id(pubkeys[1])
    opened = 0
    for recipient, sender, blob in rows:
        if recipient == anna_id and sender == alice_id:
            assert b'"t":"query"' in crypto.open_from_peer(anna_key, alice_key.public_key, blob)
            opened += 1
        elif recipient == alice_id and sender == anna_id:
            try:
                plain = crypto.open_from_peer(alice_key, PublicKey(pubkeys[1]), blob)
                assert b'"t":"answer"' in plain
            except crypto.CryptoError:
                assert b'"t":"pair_accept"' in crypto.open_anonymous(alice_key, blob)
            opened += 1
    assert opened == len(rows) - 1  # all but the code-addressed offer, which needs the code
