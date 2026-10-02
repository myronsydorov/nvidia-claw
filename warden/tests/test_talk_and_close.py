"""Talk to Custody and the brain's daily close (CONTRACTS §3 `/api/talk`, §5, §6)."""

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import httpx2 as httpx
import pytest
from fastapi.testclient import TestClient
from seed import _insert, seed_worry
from warden.app import app
from warden.brain import BrainUnavailable, GatewayBrain, TalkLimiter, clean

WORRY_ID = "w_01K6B8Z3Q4R5S6T7V8W9XA0001"
TEST_ID = "w_01K6B8Z3Q4R5S6T7V8W9XA0009"
NOW = datetime.now(UTC).isoformat()


class FakeBrain:
    def __init__(self, *replies: str | Exception) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[str, str, str]] = []

    async def chat(self, session: str, system: str, text: str) -> str:
        self.calls.append((session, system, text))
        reply = self.replies.pop(0)
        if isinstance(reply, Exception):
            raise reply
        return reply


def worry(id_: str, text: str, status: str = "watching") -> dict[str, Any]:
    return {"id": id_, "text": text, "type": "checkable", "fear": "f", "deadline": None,
            "status": status, "watcher_id": None, "resolution": None, "fear_came_true": None,
            "created_at": NOW, "updated_at": NOW}  # fmt: skip


def seed_day(db: str) -> None:
    approved = [{"at": NOW, "kind": "approved", "text": "ok"}]
    seed_worry(db, worry(WORRY_ID, "What if it rains between 16:00 and 19:00?"), approved)
    seed_worry(db, worry(TEST_ID, "TEST worry"), [*approved, {"at": NOW, "kind": "test",
                                                                "text": "t"}])  # fmt: skip
    for i, (wid, status) in enumerate([(WORRY_ID, "ok")] * 3 + [(TEST_ID, "ok")] * 2):
        row = {"at": NOW, "worry_id": wid, "watcher_id": "wt_x", "status": status}
        _insert(db, "checks", "id", f"c_{i}", row, at=NOW, worry_id=wid)


@pytest.fixture
def client(warden_test_environment: str) -> Iterator[TestClient]:
    seed_day(warden_test_environment)
    with TestClient(app) as c:
        yield c


def use(client: TestClient, brain: FakeBrain | None) -> None:
    client.app.state.brain = brain  # type: ignore[attr-defined]
    client.app.state.talk_limiter = TalkLimiter()  # type: ignore[attr-defined]
    client.app.state.close_attempt_at = None  # type: ignore[attr-defined]


# --- ledger: silence as a number ---


def test_ledger_counts_stored_checks_and_alerts_excluding_tests(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    body = client.get("/api/ledger", headers=auth_headers).json()
    assert body["checks_run"] == 3  # the test worry's 2 checks are not counted
    assert body["alerts_sent"] == 0
    assert body["checks_since"] is not None


def test_ledger_checks_since_is_null_without_checks(auth_headers: dict[str, str]) -> None:
    with TestClient(app) as c:
        body = c.get("/api/ledger", headers=auth_headers).json()
    assert (body["checks_run"], body["alerts_sent"], body["checks_since"]) == (0, 0, None)


# --- talk ---


def test_talk_goes_to_the_brain_and_returns_clean_text(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    brain = FakeBrain("I'm watching 1 worry.\x1b[31m <script>x</script>")
    use(client, brain)
    r = client.post("/api/talk", json={"text": "What are you watching?"}, headers=auth_headers)
    assert r.status_code == 200
    assert r.json()["reply"] == "I'm watching 1 worry.[31m <script>x</script>"  # escaped by app
    session, system, text = brain.calls[0]
    assert session.startswith("custody-talk-20") and text == "What are you watching?"  # per day
    assert "re-check" in system and "Only claim what a tool returned" in system


@pytest.mark.parametrize("text", ["watch https://evil.example/x", "check example.com please"])
def test_talk_refuses_links(client: TestClient, auth_headers: dict[str, str], text: str) -> None:
    brain = FakeBrain("never")
    use(client, brain)
    r = client.post("/api/talk", json={"text": text}, headers=auth_headers)
    assert r.status_code == 422 and brain.calls == []


def test_talk_is_rate_limited(client: TestClient, auth_headers: dict[str, str]) -> None:
    use(client, FakeBrain("one", "two"))
    assert client.post("/api/talk", json={"text": "hi"}, headers=auth_headers).status_code == 200
    assert client.post("/api/talk", json={"text": "hi"}, headers=auth_headers).status_code == 429


def test_talk_limiter_hourly_cap_and_busy() -> None:
    limiter = TalkLimiter()
    assert all(limiter.allow(t * 10.0) for t in range(20))
    assert not limiter.allow(205.0)  # 21st within the hour
    assert limiter.allow(3601.0 + 10)
    limiter.busy = True
    assert not limiter.allow(9999.0)


def test_talk_without_brain_or_with_brain_down_is_503(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    use(client, None)
    assert client.post("/api/talk", json={"text": "hi"}, headers=auth_headers).status_code == 503
    use(client, FakeBrain(BrainUnavailable("ConnectError")))
    assert client.post("/api/talk", json={"text": "hi"}, headers=auth_headers).status_code == 503


def test_talk_needs_the_device_token(client: TestClient) -> None:
    assert client.post("/api/talk", json={"text": "hi"}).status_code == 401


def test_talk_rejects_extra_fields_and_long_text(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    use(client, FakeBrain("x"))
    assert client.post("/api/talk", json={"text": "hi", "system": "x"},
                       headers=auth_headers).status_code == 422  # fmt: skip
    assert client.post("/api/talk", json={"text": "a" * 1001},
                       headers=auth_headers).status_code == 422  # fmt: skip


# --- daily close ---


def test_daily_close_keeps_a_note_whose_numbers_are_real(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    note = "Today I watched the rain worry. 3 checks ran, and nothing needed you."
    brain = FakeBrain(note)
    use(client, brain)
    assert client.get("/api/daily-close", headers=auth_headers).json() is None
    r = client.post("/api/daily-close", headers=auth_headers)
    assert r.status_code == 200
    body = r.json()
    assert body["text"] == note and body["checks_run"] == 3 and body["alerts_sent"] == 0
    assert "today" in brain.calls[0][1]
    assert client.get("/api/daily-close", headers=auth_headers).json()["text"] == note
    # A second one within 10 minutes is refused.
    assert client.post("/api/daily-close", headers=auth_headers).status_code == 429


def test_daily_close_discards_invented_numbers(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    use(client, FakeBrain("214 checks ran today.", "I ran 5 checks."))
    assert client.post("/api/daily-close", headers=auth_headers).status_code == 502
    assert client.get("/api/daily-close", headers=auth_headers).json() is None


def test_daily_close_retries_once(client: TestClient, auth_headers: dict[str, str]) -> None:
    use(client, FakeBrain("UNAVAILABLE", "3 checks, nothing needed you."))
    assert client.post("/api/daily-close", headers=auth_headers).status_code == 200


# --- the gateway client ---


def test_gateway_must_be_loopback() -> None:
    with pytest.raises(ValueError):
        GatewayBrain("http://100.81.50.38:18789", "t")
    GatewayBrain("http://127.0.0.1:18789", "t")


async def test_gateway_sends_token_and_reads_content() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})

    brain = GatewayBrain("http://127.0.0.1:18789", "tok", transport=httpx.MockTransport(handler))
    assert await brain.chat("s", "sys", "hi") == "hello"
    assert seen[0].headers["authorization"] == "Bearer tok"
    assert seen[0].url.path == "/v1/chat/completions"


@pytest.mark.parametrize("response", [httpx.Response(401), httpx.Response(200, json={}),
                                      httpx.Response(200, json={"choices": [{"message": {
                                          "content": "  "}}]})])  # fmt: skip
async def test_gateway_failures_are_unavailable(response: httpx.Response) -> None:
    brain = GatewayBrain(
        "http://127.0.0.1:1", "t", transport=httpx.MockTransport(lambda r: response)
    )
    with pytest.raises(BrainUnavailable):
        await brain.chat("s", "sys", "hi")


def test_clean_strips_controls_and_caps() -> None:
    assert clean("a‮b\x00c", 10) == "abc"
    assert len(clean("x" * 50, 10)) == 10


def test_talk_reply_links_are_removed(client: TestClient, auth_headers: dict[str, str]) -> None:
    use(client, FakeBrain("Fix it at https://evil.example/x or evil.example/y now."))
    reply = client.post("/api/talk", json={"text": "hi"}, headers=auth_headers).json()["reply"]
    assert "evil" not in reply and reply.count("[link removed]") == 2


def test_talk_whitespace_only_is_422(client: TestClient, auth_headers: dict[str, str]) -> None:
    brain = FakeBrain("x")
    use(client, brain)
    assert client.post("/api/talk", json={"text": "   "}, headers=auth_headers).status_code == 422
    assert brain.calls == []


def test_daily_close_refuses_a_note_with_a_link(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    use(client, FakeBrain("3 checks ran. See evil.example/x", "3 checks, www.evil.example"))
    assert client.post("/api/daily-close", headers=auth_headers).status_code == 502


def test_daily_close_failed_attempts_count_toward_the_gap(
    client: TestClient, auth_headers: dict[str, str]
) -> None:
    use(client, FakeBrain(BrainUnavailable("x"), "3 checks."))
    assert client.post("/api/daily-close", headers=auth_headers).status_code == 503
    assert client.post("/api/daily-close", headers=auth_headers).status_code == 429


async def test_gateway_ignores_proxy_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HTTP_PROXY", "http://10.9.9.9:3128")
    monkeypatch.setenv("ALL_PROXY", "http://10.9.9.9:3128")
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json={"choices": [{"message": {"content": "ok"}}]})

    brain = GatewayBrain("http://127.0.0.1:18789", "t", transport=httpx.MockTransport(handler))
    assert await brain.chat("s", "sys", "hi") == "ok"
    assert seen[0].url.host == "127.0.0.1"
