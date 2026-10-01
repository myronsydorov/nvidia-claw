"""The fixed answer vocabulary (CONTRACTS §2, ADR-0004, AGENTS invariant #5).

`enforce` is the gate every outgoing answer passes **before** it is encrypted: anything other
than exactly `{level, reason, ts}` with in-vocabulary values raises. The asking side
re-validates what it receives with the same strict model.
"""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, ValidationError

from warden.models import ReassuranceAnswer

FIELDS_SHARED = ["level", "reason", "ts"]


class VocabularyViolation(ValueError):
    """An answer had a field or value outside the fixed vocabulary. Never carries the value."""


class WireAnswer(ReassuranceAnswer):
    model_config = ConfigDict(extra="forbid", strict=True)


def enforce(candidate: object) -> ReassuranceAnswer:
    data: Any = candidate.model_dump() if isinstance(candidate, BaseModel) else candidate
    if not isinstance(data, dict) or set(data) != set(FIELDS_SHARED):
        raise VocabularyViolation("answer must have exactly the fields level, reason, ts")
    try:
        wire = WireAnswer.model_validate(data)
    except ValidationError as exc:
        # Report which fields failed, never the offending value (it may be the leak).
        fields = sorted({str(err["loc"][0]) for err in exc.errors() if err["loc"]})
        raise VocabularyViolation(f"out-of-vocabulary answer fields: {fields}") from None
    return ReassuranceAnswer(level=wire.level, reason=wire.reason, ts=wire.ts)


def unknown(ts: datetime) -> ReassuranceAnswer:
    """The null answer: says nothing about the person. Used when a rule withholds."""
    return ReassuranceAnswer(level="unknown", reason="not_enough_data", ts=ts)
