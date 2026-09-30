"""NVIDIA Build client (recorded responses via MockTransport, never the network) and replay."""

import json
import logging
from pathlib import Path

import httpx2 as httpx
import pytest
from warden.compiler.llm import (
    LLMError,
    Message,
    NvidiaClient,
    ReplayClient,
    StageSettings,
    llm_from_env,
)

KEY = "nvapi-test-key-do-not-log"
REPLAY = Path(__file__).parent.parent / "fixtures" / "llm" / "replay.json"
MESSAGES = [Message("system", "s"), Message("user", "u")]


def completion(content: str, reasoning: str | None = "thinking out loud") -> dict[str, object]:
    # The shape NVIDIA Build returns for reasoning models: content + reasoning_content.
    message: dict[str, object] = {"role": "assistant", "content": content}
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    return {"id": "chatcmpl-1", "choices": [{"index": 0, "message": message}]}


def client(handler: object, attempts: int = 3) -> NvidiaClient:
    settings = StageSettings(model="m", max_tokens=100, timeout_s=5, temperature=0)
    return NvidiaClient(
        base_url="https://llm.test/v1",
        api_key=KEY,
        stages={"triage": settings, "codegen": settings},
        attempts=attempts,
        backoff_s=0,
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
    )


async def test_returns_content_only_and_sends_the_right_request() -> None:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(200, json=completion("the answer"))

    assert await client(handler).complete("triage", MESSAGES) == "the answer"
    request = seen[0]
    assert str(request.url) == "https://llm.test/v1/chat/completions"
    assert request.headers["authorization"] == f"Bearer {KEY}"
    body = json.loads(request.content)
    assert body["model"] == "m" and body["max_tokens"] == 100
    assert body["messages"] == [
        {"role": "system", "content": "s"},
        {"role": "user", "content": "u"},
    ]


async def test_retries_429_and_5xx_then_succeeds() -> None:
    statuses = iter([429, 503])

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses, 200)
        if status != 200:
            return httpx.Response(status, headers={"retry-after": "0"})
        return httpx.Response(200, json=completion("ok"))

    assert await client(handler).complete("codegen", MESSAGES) == "ok"


async def test_retries_transport_errors() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise httpx.ReadTimeout("slow", request=request)
        return httpx.Response(200, json=completion("ok"))

    assert await client(handler).complete("codegen", MESSAGES) == "ok"


async def test_gives_up_without_leaking_the_key(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text=f"echo {request.headers['authorization']}")

    with pytest.raises(LLMError) as info:
        await client(handler, attempts=2).complete("triage", MESSAGES)
    assert "unavailable after retries" in str(info.value)
    assert KEY not in str(info.value)
    assert KEY not in caplog.text
    assert all(KEY not in str(r.__dict__) for r in caplog.records)


async def test_4xx_is_not_retried() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(401)

    with pytest.raises(LLMError, match="refused"):
        await client(handler).complete("triage", MESSAGES)
    assert calls == 1


async def test_reasoning_only_answer_is_an_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=completion("", reasoning="all the thinking, no answer"))

    with pytest.raises(LLMError, match="empty"):
        await client(handler).complete("triage", MESSAGES)


async def test_missing_key_is_an_llm_error() -> None:
    settings = StageSettings(model="m", max_tokens=1, timeout_s=1, temperature=0)
    empty = NvidiaClient("https://llm.test/v1", "", {"triage": settings, "codegen": settings})
    with pytest.raises(LLMError, match="NVIDIA_API_KEY"):
        await empty.complete("triage", MESSAGES)


async def test_replay_picks_the_case_by_keyword() -> None:
    replay = ReplayClient.from_file(str(REPLAY))
    answer = await replay.complete("triage", [Message("user", "Will the S1 train run?")])
    assert json.loads(answer)["route"] == "watch"
    assert "transit_bvg" in await replay.complete("codegen", [Message("user", "the S1 train")])
    fallback = await replay.complete("triage", [Message("user", "zzz")])
    assert "parcel" in json.loads(fallback)["fear"].lower()


def test_replay_requires_mock_sandboxes(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUSTODY_LLM_REPLAY", str(REPLAY))
    monkeypatch.setenv("CUSTODY_SANDBOX", "openshell")
    with pytest.raises(RuntimeError, match="CUSTODY_SANDBOX=mock"):
        llm_from_env()
    monkeypatch.setenv("CUSTODY_SANDBOX", "mock")
    assert isinstance(llm_from_env(), ReplayClient)
