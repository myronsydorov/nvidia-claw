"""Triage: worry text → type, the precise fear, a deadline and a route (DESIGN §4 steps 2–3)."""

import json
import logging
import re
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, ValidationError

from warden.compiler.guard import GUARD_RULE, untrusted
from warden.compiler.llm import CallDiag, LLMClient, LLMError, Message, Stage

log = logging.getLogger(__name__)

Route = Literal["watch", "person", "park"]
TriageType = Literal["checkable", "deadline", "person", "social", "uncontrollable"]


class Triage(BaseModel):
    type: TriageType
    fear: str = Field(min_length=1, max_length=200)
    deadline: AwareDatetime | None
    route: Route
    signal: str = Field(default="", max_length=300)


SYSTEM = f"""You triage worries for Custody, a calm assistant that holds on to worries for people.
Read the worry and answer with ONE JSON object and nothing else:
{{"type": "...", "fear": "...", "deadline": "...", "route": "...", "signal": "..."}}

type:
- "checkable": a fact in the world that public data or an official API can settle
  (a parcel, a train, the weather, a web page, a feed, a flight, a calendar).
- "deadline": like checkable, but it matters by a specific time.
- "person": about how someone the user cares about is doing (safe, OK, home yet).
- "social": about what other people think or feel (a friend annoyed, a boss's opinion).
- "uncontrollable": nothing observable would settle it (the economy, getting ill someday).

route: "watch" for checkable/deadline, "person" for person, "park" for social/uncontrollable.
If a checkable worry lacks what a watcher would need, still route "watch": a builder decides.

fear: the precise bad outcome in one short line, with the concrete thing and time,
e.g. "parcel 00340434161094042557 not delivered by 2026-10-02T16:00Z".
deadline: ISO 8601 UTC when the worry stops mattering, or null if none is stated or implied.
Resolve relative dates ("Friday", "tomorrow") from the current time you are given.
signal: which observable signal would settle it (e.g. "DHL tracking status"), or "".

{GUARD_RULE}"""

_THINK_RE = re.compile(r"<think>.*?(</think>|$)", re.DOTALL | re.IGNORECASE)
_RETRY_NUDGE = (
    "That was not one valid JSON object with the fields asked. Answer again with ONLY the "
    "JSON object: no reasoning, no prose, no code fence."
)


class TriageError(Exception):
    pass


def parse_triage(content: str) -> Triage:
    """The LAST JSON object in the answer that is a valid Triage.

    Reasoning models sometimes put their thinking in `content` ("Here's a thinking
    process: ..."), quoting the schema or drafting answers before the final one. The
    last valid object is the answer; `<think>` blocks are dropped first.
    """
    text = _THINK_RE.sub("", content)
    decoder = json.JSONDecoder()
    found_json = False
    last_error = ""
    best: Triage | None = None
    for start in (i for i, ch in enumerate(text) if ch == "{"):
        try:
            data, _ = decoder.raw_decode(text, start)
        except ValueError:
            continue
        if not isinstance(data, dict):
            continue
        found_json = True
        try:
            best = Triage.model_validate(data)
        except ValidationError as exc:
            last_error = ", ".join(str(e["loc"][0]) for e in exc.errors() if e["loc"])[:120]
    if best is not None:
        return best
    if not found_json:
        raise TriageError(f"no JSON object in the answer ({len(content)} chars)")
    raise TriageError(f"no valid triage object (bad fields: {last_error or '?'})")


def _messages(text: str, now: datetime) -> list[Message]:
    return [
        Message("system", SYSTEM),
        Message(
            "user",
            f"Current time: {now.isoformat()}\nThe worry, as the user wrote it:\n"
            + untrusted(text, "worry_text"),
        ),
    ]


async def _ask(
    llm: LLMClient, stage: Stage, messages: list[Message], reasons: list[str], calls: list[CallDiag]
) -> Triage | None:
    """One stage: an answer, and one re-ask if it doesn't parse. None if both fail."""
    for msgs in (messages, [*messages, Message("user", _RETRY_NUDGE)]):
        try:
            content = await llm.complete(stage, msgs)
        except LLMError as exc:
            reasons.append(str(exc))
            calls.extend(exc.calls)
            return None  # the client already retried; don't re-ask a failing endpoint
        try:
            return _consistent(parse_triage(content))
        except TriageError as exc:
            reasons.append(f"{stage}: {exc}")
    return None


async def triage(llm: LLMClient, text: str, now: datetime) -> Triage:
    """Fast model (answer + one re-ask), then once more with the code model, then give up."""
    messages = _messages(text, now)
    reasons: list[str] = []
    calls: list[CallDiag] = []
    for stage in ("triage", "triage_fallback"):
        result = await _ask(llm, stage, messages, reasons, calls)
        if result is not None:
            if stage == "triage_fallback":
                log.info("triage answered by the fallback model", extra={"reasons": reasons})
            return result
    raise LLMError("triage gave no usable answer: " + " | ".join(reasons), calls)


_ROUTE_FOR_TYPE: dict[str, Route] = {
    "checkable": "watch",
    "deadline": "watch",
    "person": "person",
    "social": "park",
    "uncontrollable": "park",
}


def _consistent(t: Triage) -> Triage:
    """The type decides the route; a mismatched route from the model is corrected."""
    return t.model_copy(update={"route": _ROUTE_FOR_TYPE[t.type]})
