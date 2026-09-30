"""Run harness for generated watchers (T-09).

A generated `run.py` may import only this module and the adapters it declared
(the compiler's static gate enforces that), so everything a watcher needs beyond
`fetch`/`parse` lives here: emitting the one WatchResult line, a little time
arithmetic, and a tiny JSON state file in /tmp. There is deliberately no way to
read a secret: adapters that need one read it themselves.
"""

import json
import sys
from datetime import UTC, datetime
from typing import Any, Literal

__all__ = [
    "emit",
    "fail",
    "now",
    "parse_time",
    "hours_until",
    "load_state",
    "save_state",
]

Status = Literal["ok", "act_now", "resolved", "error"]
_STATUSES = ("ok", "act_now", "resolved", "error")
_STATE_PATH = "/tmp/watcher_state.json"
_SUMMARY_MAX = 140


def emit(
    status: Status,
    summary: str,
    source: str,
    data: dict[str, Any] | None = None,
    next_check_s: int = 3600,
    fear_came_true: bool | None = None,
) -> None:
    """Print exactly one WatchResult JSON object to stdout (CONTRACTS §1)."""
    if status not in _STATUSES:
        raise ValueError(f"status must be one of {_STATUSES}, got {status!r}")
    result = {
        "status": status,
        "summary": " ".join(str(summary).split())[:_SUMMARY_MAX],
        "evidence": {
            "source": str(source)[:64],
            "checked_at": now().isoformat(),
            "data": data or {},
        },
        "fear_came_true": fear_came_true,
        "next_check_s": int(next_check_s),
    }
    sys.stdout.write(json.dumps(result, default=str) + "\n")
    sys.stdout.flush()


def fail(summary: str, source: str = "watcher") -> None:
    """Report that this check couldn't be done (the Warden counts it as an error)."""
    emit("error", summary, source, next_check_s=3600)


def now() -> datetime:
    return datetime.now(UTC)


def parse_time(value: str) -> datetime:
    """ISO 8601 → aware UTC datetime (a trailing Z and date-only values are accepted)."""
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def hours_until(value: str | datetime) -> float:
    target = parse_time(value) if isinstance(value, str) else value
    return (target - now()).total_seconds() / 3600


def load_state() -> dict[str, Any]:
    """What this watcher saved on its previous run ({} on the first run)."""
    try:
        with open(_STATE_PATH, encoding="utf-8") as fh:
            loaded = json.load(fh)
    except (OSError, ValueError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def save_state(state: dict[str, Any]) -> None:
    with open(_STATE_PATH, "w", encoding="utf-8") as fh:
        json.dump(state, fh, default=str)
