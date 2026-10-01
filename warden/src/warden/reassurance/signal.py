"""The "normal day" signal, v1: honest and simple (DESIGN §3, CONTRACTS §2).

A pure function of locally gathered inputs. Only the resulting `level`/`reason` pair ever
leaves the machine, and it still passes `vocabulary.enforce` and the owner's sharing rule.

Precedence (first match wins):
1. an explicit "I need help"                     → help / asked_for_help
2. a check-in in the last 3 h                    → normal / active_as_usual
3. a busy calendar event right now               → normal / do_not_disturb
4. < 3 days of activity history                  → unknown / not_enough_data
5. computer activity in the last 30 min          → normal / active_as_usual
6. a usually-active hour, but idle for ≥ 2 h     → unusual / quieter_than_usual
7. otherwise (e.g. night, a usually quiet hour)  → normal / active_as_usual

"Usually active" hours are learned from the last 14 days of activity samples: an hour of the
day counts when it saw activity on at least half of the days that have samples. Hours are UTC
on both sides of the comparison, so the learned pattern stays consistent.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta

from warden.models import ReassuranceAnswer

CHECK_IN_FRESH = timedelta(hours=3)
RECENTLY_ACTIVE = timedelta(minutes=30)
QUIET_TOO_LONG = timedelta(hours=2)
LEARNING_WINDOW = timedelta(days=14)
MIN_DAYS = 3
USUAL_SHARE = 0.5


@dataclass(frozen=True, slots=True)
class ActivitySample:
    ts: datetime
    active: bool


@dataclass(frozen=True, slots=True)
class SignalInputs:
    help_requested: bool = False
    last_check_in: datetime | None = None
    busy_now: bool = False
    samples: list[ActivitySample] = field(default_factory=list)
    idle_s: float | None = None  # live probe reading, when the machine exposes one


def usual_active_hours(now: datetime, samples: list[ActivitySample]) -> tuple[set[int], int]:
    """→ (hours of the day usually active, number of days with any sample)."""
    recent = [s for s in samples if now - LEARNING_WINDOW <= s.ts <= now]
    days = {s.ts.date() for s in recent}
    active_days_by_hour: dict[int, set[object]] = {}
    for s in recent:
        if s.active:
            active_days_by_hour.setdefault(s.ts.hour, set()).add(s.ts.date())
    if not days:
        return set(), 0
    usual = {h for h, d in active_days_by_hour.items() if len(d) / len(days) >= USUAL_SHARE}
    return usual, len(days)


def last_active(now: datetime, inputs: SignalInputs) -> datetime | None:
    candidates = [s.ts for s in inputs.samples if s.active and s.ts <= now]
    if inputs.idle_s is not None:
        candidates.append(now - timedelta(seconds=inputs.idle_s))
    return max(candidates, default=None)


def compute(now: datetime, inputs: SignalInputs) -> ReassuranceAnswer:
    def answer(level: str, reason: str) -> ReassuranceAnswer:
        return ReassuranceAnswer.model_validate({"level": level, "reason": reason, "ts": now})

    if inputs.help_requested:
        return answer("help", "asked_for_help")
    if inputs.last_check_in is not None and now - inputs.last_check_in <= CHECK_IN_FRESH:
        return answer("normal", "active_as_usual")
    if inputs.busy_now:
        return answer("normal", "do_not_disturb")

    usual, days = usual_active_hours(now, inputs.samples)
    if days < MIN_DAYS:
        return answer("unknown", "not_enough_data")

    seen = last_active(now, inputs)
    if seen is not None and now - seen <= RECENTLY_ACTIVE:
        return answer("normal", "active_as_usual")
    if now.hour in usual and (seen is None or now - seen >= QUIET_TOO_LONG):
        return answer("unusual", "quieter_than_usual")
    return answer("normal", "active_as_usual")
