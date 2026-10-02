"""Silence as a number: the check log, and the day's numbers the brain may cite.

Every stored watcher run appends one row (CONTRACTS §5 `checks_run`). Nothing here reads watched
content: a row holds ids, a time and the result's status word only.
"""

import os
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from ulid import ULID

from warden.db import Store
from warden.models import DayNumbers, Watcher, WatchingItem


def local_tz() -> ZoneInfo:
    return ZoneInfo(os.environ.get("WARDEN_TZ", "Europe/Berlin"))


async def record_check(store: Store, watcher: Watcher, status: str, at: datetime) -> None:
    stamp = at.astimezone(UTC).isoformat()
    await store.checks.put(
        f"c_{ULID()}",
        {"at": stamp, "worry_id": watcher.worry_id, "watcher_id": watcher.id, "status": status},
        at=stamp,
        worry_id=watcher.worry_id,
    )


def is_test(row: dict[str, Any]) -> bool:
    """Created to test the system (scripts/mark_test_worry.py), not one of the person's worries."""
    return any(event["kind"] == "test" for event in row["timeline"])


def is_build_failure(row: dict[str, Any]) -> bool:
    kinds = {event["kind"] for event in row["timeline"]}
    return row["worry"]["status"] == "failed" or ("failed" in kinds and "approved" not in kinds)


async def counted_checks(store: Store, test_ids: set[str]) -> list[dict[str, Any]]:
    return [c for c in await store.checks.query() if c["worry_id"] not in test_ids]


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    start = datetime.combine(day, time(0), tzinfo=local_tz())
    return start.astimezone(UTC), (start + timedelta(days=1)).astimezone(UTC)


async def day_numbers(store: Store, now: datetime) -> DayNumbers:
    """Today's real numbers (local day), test worries excluded (CONTRACTS §4 `today`)."""
    day = now.astimezone(local_tz()).date()
    start, end = _day_bounds(day)
    rows = await store.worries.query()
    test_ids = {r["worry"]["id"] for r in rows if is_test(r)}

    def today(at: str) -> bool:
        return start <= datetime.fromisoformat(at.replace("Z", "+00:00")) < end

    checks = [c for c in await counted_checks(store, test_ids) if today(c["at"])]
    counted = [r for r in rows if r["worry"]["id"] not in test_ids and not is_build_failure(r)]
    alerts = 0
    needed = 0
    for r in counted:
        events_today = [e for e in r["timeline"] if today(e["at"])]
        alerts += sum(1 for e in events_today if e["kind"] == "act_now")
        needed += any(e["kind"] in ("act_now", "failed") for e in events_today)
    checked_ids = {c["worry_id"] for c in checks}
    watching = [
        WatchingItem(id=r["worry"]["id"], text=r["worry"]["text"])
        for r in counted
        if r["worry"]["status"] in ("watching", "needs_you") or r["worry"]["id"] in checked_ids
    ]
    return DayNumbers(
        date=day.isoformat(),
        checks_run=len(checks),
        alerts_sent=alerts,
        needed_you=needed,
        watching=watching,
    )
