"""LLM access for the compiler: NVIDIA Build (OpenAI-compatible) or a recorded replay.

`NvidiaClient` reads `choices[0].message.content` only — any `reasoning_content`
the model returns is ignored. The API key is sent in the Authorization header and
nowhere else: it is never logged and never placed in an exception message. Logs
carry the stage, model, HTTP status and latency, never prompt or completion text.

`ReplayClient` serves recorded completions (dev and e2e without a key). It only
replaces the network call: the rest of the compiler — gate, policy generation and
dry run — still runs on what it returns. It is refused unless CUSTODY_SANDBOX=mock.
"""

import asyncio
import json
import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

import httpx2 as httpx

log = logging.getLogger(__name__)

Stage = Literal["triage", "codegen"]

DEFAULT_BASE_URL = "https://integrate.api.nvidia.com/v1"
DEFAULT_MODEL_FAST = "nvidia/nemotron-3.5-lightning-30b-a3b"
DEFAULT_MODEL_CODE = "nvidia/nemotron-3-super-120b-a12b"


@dataclass(frozen=True, slots=True)
class Message:
    role: Literal["system", "user", "assistant"]
    content: str


class LLMError(Exception):
    """The model could not be reached or gave no usable answer. Message never holds secrets."""


class LLMClient(Protocol):
    async def complete(self, stage: Stage, messages: list[Message]) -> str: ...


@dataclass(frozen=True, slots=True)
class StageSettings:
    model: str
    max_tokens: int
    timeout_s: float
    temperature: float


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
    ) -> None:
        self._url = base_url.rstrip("/") + "/chat/completions"
        self._api_key = api_key
        self._stages = stages
        self._attempts = attempts
        self._backoff_s = backoff_s
        self._transport = transport

    @classmethod
    def from_env(cls) -> "NvidiaClient":
        return cls(
            base_url=os.environ.get("CUSTODY_LLM_BASE_URL") or DEFAULT_BASE_URL,
            api_key=os.environ.get("NVIDIA_API_KEY", ""),
            stages={
                "triage": StageSettings(
                    model=os.environ.get("CUSTODY_MODEL_FAST") or DEFAULT_MODEL_FAST,
                    max_tokens=1500,
                    timeout_s=60,
                    temperature=0.1,
                ),
                "codegen": StageSettings(
                    model=os.environ.get("CUSTODY_MODEL_CODE") or DEFAULT_MODEL_CODE,
                    max_tokens=6000,
                    timeout_s=180,
                    temperature=0.2,
                ),
            },
        )

    async def complete(self, stage: Stage, messages: list[Message]) -> str:
        if not self._api_key:
            raise LLMError("NVIDIA_API_KEY is not set")
        settings = self._stages[stage]
        body = {
            "model": settings.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": settings.max_tokens,
            "temperature": settings.temperature,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self._api_key}", "Accept": "application/json"}
        last_problem = "no attempt made"
        async with httpx.AsyncClient(
            timeout=settings.timeout_s, transport=self._transport
        ) as client:
            for attempt in range(1, self._attempts + 1):
                started = time.monotonic()
                try:
                    response = await client.post(self._url, json=body, headers=headers)
                except httpx.TransportError as exc:
                    # Type only: transport errors can echo request details.
                    last_problem = f"network error ({type(exc).__name__})"
                    status = None
                else:
                    status = response.status_code
                    log.info(
                        "llm call",
                        extra={
                            "stage": stage,
                            "model": settings.model,
                            "status": status,
                            "attempt": attempt,
                            "latency_ms": int((time.monotonic() - started) * 1000),
                        },
                    )
                    if status == 200:
                        return _content(response)
                    last_problem = f"HTTP {status}"
                    if status not in self.RETRY_STATUSES:
                        raise LLMError(f"{stage}: model endpoint refused the request ({status})")
                if attempt < self._attempts:
                    delay = self._backoff_s * 2 ** (attempt - 1)
                    if status is not None:
                        delay = max(delay, _retry_after(response))
                    await asyncio.sleep(min(delay, 60.0))
        raise LLMError(f"{stage}: model endpoint unavailable after retries ({last_problem})")


def _retry_after(response: httpx.Response) -> float:
    try:
        return float(response.headers.get("retry-after", "0"))
    except ValueError:
        return 0.0


def _content(response: httpx.Response) -> str:
    try:
        payload = response.json()
        content = payload["choices"][0]["message"]["content"]
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise LLMError("model response had no message content") from exc
    if not isinstance(content, str) or not content.strip():
        raise LLMError("model response had empty message content")
    return content


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
        answer = case.get(stage)
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
