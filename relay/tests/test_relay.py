import base64
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from relay.app import MAX_PER_MAILBOX, create_app

from relay import app as relay_app
from relay import app as relay_module

ALICE = "a" * 32
BOB = "b" * 32


@pytest.fixture
def db_path(tmp_path: Path) -> str:
    return str(tmp_path / "relay.db")


@pytest.fixture
def client(db_path: str) -> Iterator[TestClient]:
    with TestClient(create_app(db_path)) as c:
        yield c


def _b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode()


def test_post_then_get_round_trips_bytes_exactly(client: TestClient) -> None:
    response = client.post(
        f"/v1/mailbox/{BOB}", json={"ciphertext": _b64(b"\x00\x01opaque"), "sender_key_id": ALICE}
    )
    assert response.status_code == 202
    [message] = client.get(f"/v1/mailbox/{BOB}").json()
    assert message["id"] == response.json()["id"]
    assert base64.b64decode(message["ciphertext"]) == b"\x00\x01opaque"
    assert message["sender_key_id"] == ALICE
    assert client.get(f"/v1/mailbox/{ALICE}").json() == []


def test_since_returns_only_newer_messages(client: TestClient) -> None:
    ids = [
        client.post(
            f"/v1/mailbox/{BOB}", json={"ciphertext": _b64(bytes([i])), "sender_key_id": ALICE}
        ).json()["id"]
        for i in range(3)
    ]
    newer = client.get(f"/v1/mailbox/{BOB}", params={"since": ids[0]}).json()
    assert [m["id"] for m in newer] == ids[1:]


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/v1/mailbox/NOT-A-KEY-ID", {"ciphertext": "AA==", "sender_key_id": ALICE}),
        (f"/v1/mailbox/{BOB}", {"ciphertext": "AA==", "sender_key_id": "x"}),
        (f"/v1/mailbox/{BOB}", {"ciphertext": "not base64!", "sender_key_id": ALICE}),
        (f"/v1/mailbox/{BOB}", {"ciphertext": "AA==", "sender_key_id": ALICE, "note": "hi"}),
        (f"/v1/mailbox/{BOB}", {"ciphertext": "", "sender_key_id": ALICE}),
    ],
)
def test_rejects_malformed_posts(client: TestClient, path: str, body: dict[str, str]) -> None:
    assert client.post(path, json=body).status_code == 422


@pytest.mark.parametrize("size", [4097, 6000])
def test_rejects_oversized_ciphertext_with_413(client: TestClient, size: int) -> None:
    body = {"ciphertext": _b64(b"x" * size), "sender_key_id": ALICE}
    assert client.post(f"/v1/mailbox/{BOB}", json=body).status_code == 413


def test_accepts_exactly_the_cap(client: TestClient) -> None:
    body = {"ciphertext": _b64(b"x" * 4096), "sender_key_id": ALICE}
    assert client.post(f"/v1/mailbox/{BOB}", json=body).status_code == 202


def test_mailbox_is_capped(client: TestClient, db_path: str) -> None:
    for i in range(MAX_PER_MAILBOX + 5):
        client.post(
            f"/v1/mailbox/{BOB}",
            json={"ciphertext": _b64(i.to_bytes(2, "big")), "sender_key_id": ALICE},
        )
    messages = client.get(f"/v1/mailbox/{BOB}").json()
    assert len(messages) == MAX_PER_MAILBOX
    assert base64.b64decode(messages[0]["ciphertext"]) == (5).to_bytes(2, "big")


def test_expired_messages_are_not_served_and_get_purged(client: TestClient, db_path: str) -> None:
    client.post(f"/v1/mailbox/{BOB}", json={"ciphertext": "AA==", "sender_key_id": ALICE})
    old = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE messages SET ts = ?", (old,))
    conn.commit()
    conn.close()
    assert client.get(f"/v1/mailbox/{BOB}").json() == []
    client.post(f"/v1/mailbox/{ALICE}", json={"ciphertext": "AQ==", "sender_key_id": BOB})
    conn = sqlite3.connect(db_path)
    (count,) = conn.execute("SELECT COUNT(*) FROM messages").fetchone()
    conn.close()
    assert count == 1


def test_no_schema_routes_are_exposed(client: TestClient) -> None:
    for path in ("/docs", "/openapi.json", "/redoc"):
        assert client.get(path).status_code == 404


def test_module_app_exists() -> None:
    assert relay_app.app.title == "Custody relay"


def test_a_huge_body_is_refused_before_it_is_read(client: TestClient) -> None:
    response = client.post(
        f"/v1/mailbox/{BOB}",
        content=b"{" + b" " * (20 * 1024) + b"}",
        headers={"content-type": "application/json"},
    )
    assert response.status_code == 413


def test_the_relay_has_a_global_cap(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(relay_module, "MAX_TOTAL_MESSAGES", 3)
    for i in range(3):
        mailbox = f"{i:032x}"
        body = {"ciphertext": "AA==", "sender_key_id": ALICE}
        assert client.post(f"/v1/mailbox/{mailbox}", json=body).status_code == 202
    body = {"ciphertext": "AA==", "sender_key_id": ALICE}
    assert client.post(f"/v1/mailbox/{BOB}", json=body).status_code == 507


def test_since_is_bounded(client: TestClient) -> None:
    assert client.get(f"/v1/mailbox/{BOB}", params={"since": 2**64}).status_code == 422
