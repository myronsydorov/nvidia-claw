"""The daily close (CONTRACTS §6): once a day the brain writes a short note for Home.

The brain gathers the day's numbers with its own MCP tool (`today`). The Warden then checks the
note against the same numbers, computed independently, and keeps it only if every number in it
is real. Otherwise it asks once more, and then stores nothing: no note beats a wrong one.
"""

import asyncio
import logging
import os
from collections.abc import Callable
from datetime import UTC, datetime, time
from typing import Any

from warden.brain import (
    CLOSE_PROMPT,
    CLOSE_SYSTEM,
    NOTE_MAX,
    Brain,
    BrainUnavailable,
    clean,
    note_is_true,
)
from warden.checks import day_numbers, local_tz
from warden.db import Store
from warden.models import DailyClose

log = logging.getLogger(__name__)

ATTEMPTS = 2


def close_lock(app: Any) -> asyncio.Lock:
    """One daily-close turn at a time, whether the app or the evening timer asked."""
    lock: asyncio.Lock | None = getattr(app.state, "close_lock", None)
    if lock is None:
        lock = app.state.close_lock = asyncio.Lock()
    return lock


class NoteNotConfirmed(Exception):
    """The brain's note named a number its tools didn't confirm; it was discarded."""


async def write_close(store: Store, brain: Brain, now: datetime) -> DailyClose:
    for attempt in range(ATTEMPTS):
        numbers = await day_numbers(store, now)
        note = clean(
            await brain.chat(f"custody-daily-close-{numbers.date}-{attempt}", CLOSE_SYSTEM,
                             CLOSE_PROMPT),
            NOTE_MAX + 1,
        )  # fmt: skip
        # Re-count after the brain answered: a check may have landed while it wrote.
        after = await day_numbers(store, now)
        if note_is_true(note, numbers) or note_is_true(note, after):
            close = DailyClose(
                date=after.date,
                text=note,
                written_at=datetime.now(UTC),
                checks_run=after.checks_run,
                alerts_sent=after.alerts_sent,
                needed_you=after.needed_you,
            )
            await store.daily_close.put(close.date, close.model_dump(mode="json"))
            return close
        log.warning("daily close discarded: unconfirmed number", extra={"attempt": attempt})
    raise NoteNotConfirmed


async def latest_close(store: Store) -> DailyClose | None:
    rows = await store.daily_close.query()
    if not rows:
        return None
    return DailyClose.model_validate(max(rows, key=lambda r: r["date"]))


def close_time() -> time:
    hh, _, mm = os.environ.get("WARDEN_DAILY_CLOSE_AT", "21:00").partition(":")
    return time(int(hh), int(mm or 0))


async def due(store: Store, now: datetime) -> bool:
    local = now.astimezone(local_tz())
    if local.time() < close_time():
        return False
    existing = await store.daily_close.get(local.date().isoformat())
    if existing is None:
        return True
    written = datetime.fromisoformat(existing["written_at"]).astimezone(local_tz())
    return written.time() < close_time()  # only the "now" note so far: write the evening one


async def run_forever(
    app: Any,
    store: Store,
    brain: Brain,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    poll_s: float = 60,
) -> None:
    failed_on: str | None = None  # don't retry a failed evening close every minute
    while True:
        now = clock()
        today = now.astimezone(local_tz()).date().isoformat()
        try:
            if failed_on != today and await due(store, now):
                async with close_lock(app):
                    await write_close(store, brain, now)
        except (BrainUnavailable, NoteNotConfirmed) as exc:
            failed_on = today
            log.warning("daily close not written", extra={"error": type(exc).__name__})
        except Exception:
            log.exception("daily close failed")
            failed_on = today
        await asyncio.sleep(poll_s)
