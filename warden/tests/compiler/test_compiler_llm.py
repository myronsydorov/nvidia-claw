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


def completion(
    content: str | None, reasoning: str | None = "thinking out loud", finish: str = "stop"
) -> dict[str, object]:
    # The shape NVIDIA Build returns for reasoning models: content + reasoning_content.
    message: dict[str, object] = {"role": "assistant", "content": content}
    if reasoning is not None:
        message["reasoning_content"] = reasoning
    return {
        "id": "chatcmpl-1",
        "choices": [{"index": 0, "message": message, "finish_reason": finish}],
    }


def client(
    handler: object,
    attempts: int = 3,
    settings: StageSettings | None = None,
    sleeps: list[float] | None = None,
    backoff_s: float = 0,
) -> NvidiaClient:
    settings = settings or StageSettings(model="m", max_tokens=100, timeout_s=5, temperature=0)

    async def record_sleep(delay: float) -> None:
        if sleeps is not None:
            sleeps.append(delay)

    return NvidiaClient(
        base_url="https://llm.test/v1",
        api_key=KEY,
        stages={"triage": settings, "triage_fallback": settings, "codegen": settings},
        attempts=attempts,
        backoff_s=backoff_s,
        transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
        sleep=record_sleep,
        jitter=lambda: 1.0,
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
    assert "no usable answer after 2 attempts" in str(info.value)
    assert "http=503" in str(info.value)
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


# --- diagnostics ---


async def test_every_attempt_is_diagnosed_without_the_key(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.INFO)
    statuses = iter([503])

    def handler(request: httpx.Request) -> httpx.Response:
        if next(statuses, 200) == 503:
            return httpx.Response(503)
        return httpx.Response(200, json=completion("answer", reasoning="r" * 42))

    llm = client(handler)
    assert await llm.complete("triage", MESSAGES) == "answer"
    first, second = llm.calls
    assert (first.outcome, first.status, first.attempt) == ("http_error", 503, 1)
    assert (second.outcome, second.status, second.finish_reason) == ("ok", 200, "stop")
    assert (second.content_chars, second.reasoning_chars) == (6, 42)
    assert "http=503" in first.line() and "finish=stop" in second.line()
    records = [r for r in caplog.records if r.getMessage() == "llm call"]
    assert [r.__dict__["outcome"] for r in records] == ["http_error", "ok"]
    assert all(KEY not in str(r.__dict__) for r in caplog.records)


async def test_timeout_is_diagnosed_and_all_four_attempts_are_used() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    llm = client(handler, attempts=4)
    with pytest.raises(LLMError) as info:
        await llm.complete("codegen", MESSAGES)
    assert [c.outcome for c in info.value.calls] == ["timeout"] * 4
    assert "timeout" in str(info.value)


async def test_empty_content_is_retried() -> None:
    answers = iter([completion(None, reasoning="all thinking"), completion("done")])

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=next(answers))

    llm = client(handler)
    assert await llm.complete("triage", MESSAGES) == "done"
    assert [c.outcome for c in llm.calls] == ["empty", "ok"]


# --- backoff ---


async def test_backoff_is_exponential_with_jitter_and_honours_retry_after() -> None:
    statuses = iter([429, 502, 503])

    def handler(request: httpx.Request) -> httpx.Response:
        status = next(statuses, 200)
        if status == 429:
            return httpx.Response(429, headers={"retry-after": "7"})
        if status != 200:
            return httpx.Response(status)
        return httpx.Response(200, json=completion("ok"))

    sleeps: list[float] = []
    llm = client(handler, attempts=4, sleeps=sleeps, backoff_s=2.0)
    assert await llm.complete("triage", MESSAGES) == "ok"
    # jitter=1.0 → 100% of each step (2, 4, 8 s); the 429's Retry-After (7 s) wins over 2 s.
    assert sleeps == [7.0, 4.0, 8.0]


def test_jitter_stays_within_half_to_full_step() -> None:
    llm = NvidiaClient("https://x.test/v1", KEY, {}, backoff_s=2.0, jitter=lambda: 0.0)
    assert llm._delay(3, None) == 4.0  # 50% of the 8 s step
    llm = NvidiaClient("https://x.test/v1", KEY, {}, backoff_s=2.0, jitter=lambda: 1.0)
    assert llm._delay(10, None) == 60.0  # capped


# --- length cut-offs (reasoning tokens count against max_tokens) ---


async def test_length_cutoff_with_empty_content_retries_with_a_higher_limit() -> None:
    seen: list[int] = []
    answers = iter([completion(None, finish="length"), completion("{}", finish="stop")])

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content)["max_tokens"])
        return httpx.Response(200, json=next(answers))

    settings = StageSettings("m", max_tokens=2500, timeout_s=5, temperature=0, max_tokens_cap=8000)
    sleeps: list[float] = []
    llm = client(handler, settings=settings, sleeps=sleeps)
    assert await llm.complete("triage", MESSAGES) == "{}"
    assert seen == [2500, 5000]
    assert sleeps == []  # not a server problem: no backoff
    assert llm.calls[0].outcome == "length"


async def test_length_cutoff_mid_reasoning_also_retries_and_stops_at_the_cap() -> None:
    seen: list[int] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(json.loads(request.content)["max_tokens"])
        return httpx.Response(
            200, json=completion("Here's a thinking process: ...", finish="length")
        )

    settings = StageSettings("m", max_tokens=2500, timeout_s=5, temperature=0, max_tokens_cap=8000)
    llm = client(handler, attempts=4, settings=settings)
    # At the cap, the truncated text is returned for the caller's parser to judge.
    assert await llm.complete("triage", MESSAGES) == "Here's a thinking process: ..."
    assert seen == [2500, 5000, 8000]


# --- reasoning off ---


async def test_thinking_off_is_sent_and_dropped_if_the_endpoint_rejects_it() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        bodies.append(body)
        if "chat_template_kwargs" in body:
            return httpx.Response(400, json={"error": "unknown field chat_template_kwargs"})
        return httpx.Response(200, json=completion("ok"))

    settings = StageSettings("m", max_tokens=100, timeout_s=5, temperature=0, thinking_off=True)
    llm = client(handler, settings=settings)
    assert await llm.complete("triage", MESSAGES) == "ok"
    assert bodies[0]["chat_template_kwargs"] == {"enable_thinking": False}
    assert "chat_template_kwargs" not in bodies[1]
    assert await llm.complete("triage", MESSAGES) == "ok"  # remembered: no second 400
    assert len(bodies) == 3


async def test_thinking_is_left_alone_for_codegen_settings() -> None:
    bodies: list[dict[str, object]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        bodies.append(json.loads(request.content))
        return httpx.Response(200, json=completion("ok"))

    await client(handler).complete("codegen", MESSAGES)
    assert "chat_template_kwargs" not in bodies[0]


def test_env_settings_meet_the_reliability_floor(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUSTODY_MODEL_FAST", "fast-model")
    monkeypatch.setenv("CUSTODY_MODEL_CODE", "code-model")
    stages = NvidiaClient.from_env()._stages
    assert stages["triage"].model == "fast-model" and stages["triage"].thinking_off
    assert stages["triage"].max_tokens >= 2000
    assert stages["triage_fallback"].model == "code-model"
    assert all(s.timeout_s >= 120 for s in stages.values())
    assert NvidiaClient.from_env()._attempts == 4
