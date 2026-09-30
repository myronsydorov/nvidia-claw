"""Triage: worry text → type, the precise fear, a deadline and a route (DESIGN §4 steps 2–3)."""

import json
import re
from datetime import datetime
from typing import Literal

from pydantic import AwareDatetime, BaseModel, Field, ValidationError

from warden.compiler.guard import GUARD_RULE, untrusted
from warden.compiler.llm import LLMClient, LLMError, Message

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

_JSON_RE = re.compile(r"\{.*\}", re.DOTALL)


class TriageError(Exception):
    pass


def parse_triage(content: str) -> Triage:
    match = _JSON_RE.search(content)
    if match is None:
        raise TriageError("no JSON object in the answer")
    try:
        data = json.loads(match.group(0))
        return Triage.model_validate(data)
    except (ValueError, ValidationError) as exc:
        raise TriageError(f"invalid triage JSON: {type(exc).__name__}") from exc


def _messages(text: str, now: datetime) -> list[Message]:
    return [
        Message("system", SYSTEM),
        Message(
            "user",
            f"Current time: {now.isoformat()}\nThe worry, as the user wrote it:\n"
            + untrusted(text, "worry_text"),
        ),
    ]


async def triage(llm: LLMClient, text: str, now: datetime) -> Triage:
    """One re-ask on an unparseable answer, then give up (the caller parks honestly)."""
    messages = _messages(text, now)
    content = await llm.complete("triage", messages)
    try:
        return _consistent(parse_triage(content))
    except TriageError:
        messages += [
            Message("assistant", content[:4000]),
            Message("user", "That was not one valid JSON object with the fields asked. Try again."),
        ]
        content = await llm.complete("triage", messages)
        try:
            return _consistent(parse_triage(content))
        except TriageError as exc:
            raise LLMError("triage gave no usable answer") from exc


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
