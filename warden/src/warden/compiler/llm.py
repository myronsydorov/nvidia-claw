"""LLM access for the compiler: NVIDIA Build (OpenAI-compatible) or a recorded replay.

`NvidiaClient` reads `choices[0].message.content` only — any `reasoning_content`
the model returns is ignored (only its length is logged). The API key is sent in the
Authorization header and nowhere else: it is never logged and never placed in an
exception message. Every attempt is recorded as a `CallDiag` (HTTP status, outcome,
finish_reason, latency, token limit, content/reasoning sizes) in logs and on
`LLMError.calls`, never prompt or completion text.

Reliability: 429/5xx/timeouts/network errors retry with jittered exponential backoff
(honouring Retry-After), up to 4 attempts; a `length` cut-off retries straight away
with a doubled max_tokens; triage asks for reasoning off via the documented
`chat_template_kwargs: {"enable_thinking": false}`, dropped automatically if the
endpoint answers 400 to it.

`ReplayClient` serves recorded completions (dev and e2e without a key). It only
replaces the network call: the rest of the compiler — gate, policy generation and
dry run — still runs on what it returns. It is refused unless CUSTODY_SANDBOX=mock.
"""

import asyncio
import json
import logging
import os
import random
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Protocol

import httpx2 as httpx

log = logging.getLogger(__name__)

Stage = Literal["triage", "triage_fallback", "codegen"]

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL_FAST = "nvidia/nemotron-3.5-lightning-30b-a3b"
DEFAULT_MODEL_CODE = "nvidia/nemotron-3-super-120b-a12b"

# Why a single HTTP attempt did not give usable content (or "ok").
Outcome = Literal["ok", "http_error", "timeout", "network", "bad_json", "empty", "length"]


@dataclass(frozen=True, slots=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str


@dataclass(frozen=True, slots=True)
class CallDiag:
    """One HTTP attempt, for logs and the eval table. Never prompt/completion text or the key."""

    stage: Stage
    model: str
    attempt: int
    outcome: Outcome
    status: int | None
    finish_reason: str | None
    latency_ms: int
    max_tokens: int
    content_chars: int
    reasoning_chars: int
    thinking_off: bool

    def line(self) -> str:
        return (
            f"{self.stage}#{self.attempt} {self.outcome} http={self.status or '-'} "
            f"finish={self.finish_reason or '-'} {self.latency_ms}ms max_tokens={self.max_tokens} "
            f"content={self.content_chars}c reasoning={self.reasoning_chars}c"
            + (" thinking=off" if self.thinking_off else "")
        )


class LLMError(Exception):
    """The model could not be reached or gave no usable answer. Message never holds secrets."""

    def __init__(self, message: str, calls: list[CallDiag] | None = None) -> None:
        super().__init__(message)
        self.calls = calls or []


class LLMClient(Protocol):
    async def complete(self, stage: Stage, messages: list[Message]) -> str: ...


@dataclass(frozen=True, slots=True)
class StageSettings:
    model: str
    max_tokens: int
    timeout_s: float
    temperature: float
    # Documented for both Nemotron models: chat_template_kwargs {"enable_thinking": false}
    # (HF model card for 3.5 Lightning; NVIDIA API reference for 3 Super).
    thinking_off: bool = False
    max_tokens_cap: int = 16000  # ceiling when a "length" cut-off makes us raise the limit


class NvidiaClient:
    RETRY_STATUSES = frozenset({429, 500, 502, 503, 504})

    def __init__(
        self,
        base_url: str,
        api_key: str,
        stages: dict[Stage, StageSettings],
        attempts: int = 4,
        backoff_s: float = 2.0,
        transport: httpx.AsyncBaseTransport | None = None,
        sleep: Callable[[float], Awaitable[None]] = asyncio.sleep,
        jitter: Callable[[], float] = random.random,
    ) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._api_key = api_key
        self._stages = stages
        self._attempts = attempts
        self._backoff_s = backoff_s
        self._transport = transport
        self._sleep = sleep
        self._jitter = jitter
        self._thinking_flag_rejected = False  # the endpoint 400'd on chat_template_kwargs once
        self.calls: list[CallDiag] = []  # every attempt this client made, for the eval

    @classmethod
    def from_env(cls) -> "NvidiaClient":
        fast = os.environ.get("CUSTODY_MODEL_FAST") or DEFAULT_MODEL_FAST
        code = os.environ.get("CUSTODY_MODEL_CODE") or DEFAULT_MODEL_CODE
        return cls(
            base_url=os.environ.get("CUSTODY_LLM_BASE_URL") or DEFAULT_BASE_URL,
            api_key=os.environ.get("NVIDIA_API_KEY", ""),
            stages={
                # Triage is a small JSON answer: reasoning off, but budget for it anyway in
                # case the endpoint ignores the flag (reasoning tokens count against max_tokens).
                "triage": StageSettings(
                    model=fast,
                    max_tokens=2500,
                    timeout_s=120,
                    temperature=0.1,
                    thinking_off=True,
                    max_tokens_cap=8000,
                ),
                "triage_fallback": StageSettings(
                    model=code,
                    max_tokens=4000,
                    timeout_s=180,
                    temperature=0.1,
                    thinking_off=True,
                    max_tokens_cap=12000,
                ),
                "codegen": StageSettings(
                    model=code,
                    max_tokens=6000,
                    timeout_s=180,
                    temperature=0.2,
                    max_tokens_cap=16000,
                ),
            },
        )

    async def complete(self, stage: Stage, messages: list[Message]) -> str:
        if not self._api_key:
            raise LLMError("NVIDIA_API_KEY is not set")
        settings = self._stages[stage]
        max_tokens = settings.max_tokens
        headers = {"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"}
        calls: list[CallDiag] = []
        async with httpx.AsyncClient(
            timeout=settings.timeout_s, transport=self._transport
        ) as client:
            for attempt in range(1, self._attempts + 1):
                thinking_off = settings.thinking_off and not self._thinking_flag_rejected
                body: dict[str, object] = {
                    "model": settings.model,
                    "messages": [{"role": m.role, "content": m.content} for m in messages],
                    "max_tokens": max_tokens,
                    "temperature": settings.temperature,
                    "stream": False,
                }
                if thinking_off:
                    body["chat_template_kwargs"] = {"enable_thinking": False}
                started = time.monotonic()
                response: httpx.Response | None = None
                content: str | None = None
                finish: str | None = None
                reasoning_chars = 0
                try:
                    response = await client.post(self._url, json=body, headers=headers)
                except httpx.TimeoutException:
                    outcome: Outcome = "timeout"
                except httpx.TransportError:
                    outcome = "network"  # type only: transport errors can echo request details
                else:
                    if response.status_code != 200:
                        outcome = "http_error"
                    else:
                        outcome, content, finish, reasoning_chars = _read(response)
                diag = CallDiag(
                    stage=stage,
                    model=settings.model,
                    attempt=attempt,
                    outcome=outcome,
                    status=response.status_code if response is not None else None,
                    finish_reason=finish,
                    latency_ms=int((time.monotonic() - started) * 1000),
                    max_tokens=max_tokens,
                    content_chars=len(content or ""),
                    reasoning_chars=reasoning_chars,
                    thinking_off=thinking_off,
                )
                calls.append(diag)
                self.calls.append(diag)
                log.info("llm call", extra=asdict(diag))

                if outcome == "ok" and content is not None:
                    return content
                if outcome == "length":
                    # Cut off (reasoning counts against max_tokens): retry at once with more room.
                    if max_tokens < settings.max_tokens_cap:
                        max_tokens = min(max_tokens * 2, settings.max_tokens_cap)
                        continue
                    if content:
                        return content  # as good as it gets; the caller's parser decides
                    continue
                if outcome == "http_error" and response is not None:
                    status = response.status_code
                    if status == 400 and thinking_off:
                        # The endpoint may not accept chat_template_kwargs: drop it, retry now.
                        self._thinking_flag_rejected = True
                        continue
                    if status not in self.RETRY_STATUSES:
                        raise LLMError(
                            f"{stage}: model endpoint refused the request (HTTP {status})", calls
                        )
                if attempt < self._attempts:
                    await self._sleep(self._delay(attempt, response))
        last = calls[-1] if calls else None
        cause = last.line() if last else "no attempt made"
        raise LLMError(f"{stage}: no usable answer after {len(calls)} attempts ({cause})", calls)

    def _delay(self, attempt: int, response: httpx.Response | None) -> float:
        """Exponential backoff with jitter (50–100% of the step), never below Retry-After."""
        step = self._backoff_s * 2.0 ** (attempt - 1)
        delay = step * (0.5 + 0.5 * self._jitter())
        if response is not None:
            delay = max(delay, _retry_after(response))
        return min(delay, 60.0)


def _retry_after(response: httpx.Response) -> float:
    try:
        return float(response.headers.get("retry-after", "0"))
    except ValueError:
        return 0.0


def _read(response: httpx.Response) -> tuple[Outcome, str | None, str | None, int]:
    """(outcome, content, finish_reason, reasoning_chars). Only message.content is ever used."""
    try:
        choice = response.json()["choices"][0]
        message = choice["message"]
    except (ValueError, KeyError, IndexError, TypeError):
        return "bad_json", None, None, 0
    content = message.get("content") if isinstance(message, dict) else None
    reasoning = message.get("reasoning_content") if isinstance(message, dict) else None
    finish = choice.get("finish_reason") if isinstance(choice, dict) else None
    reasoning_chars = len(reasoning) if isinstance(reasoning, str) else 0
    text = content if isinstance(content, str) else None
    if finish == "length":
        return "length", text, finish, reasoning_chars
    if not text or not text.strip():
        return "empty", None, finish, reasoning_chars
    return "ok", text, finish, reasoning_chars


class ReplayClient:
    """Serves recorded completions: `{"cases": [{"match": [...], "triage": str, "codegen": str}]}`.

    The case is picked by the first `match` keyword found in the worry text (inside
    the user message); the first case is the fallback.
    """

    def __init__(self, cases: list[dict[str, object]]) -> None:
        if not cases:
            raise ValueError("replay file has no cases")
        self._cases = cases

    @classmethod
    def from_file(cls, path: str) -> "ReplayClient":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls(list(data["cases"]))

    async def complete(self, stage: Stage, messages: list[Message]) -> str:
        text = "\n".join(m.content for m in messages if m.role == "user").lower()
        case = next(
            (
                c
                for c in self._cases
                if any(str(k).lower() in text for k in _as_list(c.get("match")))
            ),
            self._cases[0],
        )
        answer = case.get("triage" if stage == "triage_fallback" else stage)
        if not isinstance(answer, str):
            raise LLMError(f"replay case has no {stage} response")
        return answer


def _as_list(value: object) -> list[object]:
    return list(value) if isinstance(value, list) else []


def llm_from_env() -> LLMClient:
    replay = os.environ.get("CUSTODY_LLM_REPLAY")
    if replay:
        if os.environ.get("CUSTODY_SANDBOX") != "mock":
            raise RuntimeError("CUSTODY_LLM_REPLAY requires CUSTODY_SANDBOX=mock")
        return ReplayClient.from_file(replay)
    return NvidiaClient.from_env()
