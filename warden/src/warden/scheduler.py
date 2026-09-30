"""T-10: run active watchers in their sandboxes and speak up only when the person must act.

Every run goes through the SandboxDriver (AGENTS.md invariant #3). A watcher's stdout is
untrusted data: it is only ever parsed into a WatchResult, never fed to a model.
Silence is the default: an `ok` result changes live status and nothing else.
"""

import asyncio
import json
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal, Protocol

from pydantic import ValidationError

from warden.db import Store
from warden.events import EventBus
from warden.models import Evidence, TimelineEvent, Watcher, WatchResult, Worry
from warden.sandbox.driver import SandboxDriver
from warden.worry_rows import parse_row, save_watcher, save_worry

log = logging.getLogger(__name__)

RUN_COMMAND = ["python3", "/w/run.py"]
MIN_NEXT_CHECK_S = 300  # a watcher can't ask to be re-run sooner: no "check again" loops
MAX_NEXT_CHECK_S = 86400
ERRORS_BEFORE_PAUSE = 3
MAX_STDOUT_CHARS = 64 * 1024  # anything bigger is not a WatchResult; don't even parse it
MAX_EVIDENCE_SOURCE_CHARS = 64
MAX_EVIDENCE_DATA_CHARS = 4096  # watched content must not be stored verbatim
ASK_OUTCOME_TEXT = "Did what you feared happen?"

PushKind = Literal["act_now", "ask_outcome", "watcher_paused"]


class Clock(Protocol):
    def now(self) -> datetime: ...


class SystemClock:
    def now(self) -> datetime:
        return datetime.now(UTC)


class PushNotifier(Protocol):
    async def notify(self, kind: PushKind, worry_id: str, text: str) -> None: ...


class LogPushNotifier:
    """Stub until T-18 (web push). Logs the kind and worry only, never the text."""

    async def notify(self, kind: PushKind, worry_id: str, text: str) -> None:
        log.info("push stub", extra={"kind": kind, "worry_id": worry_id})


@dataclass
class _ScheduleEntry:
    next_run_at: datetime | None = None
    consecutive_errors: int = 0


class Scheduler:
    def __init__(
        self,
        store: Store,
        driver: SandboxDriver,
        events: EventBus,
        clock: Clock,
        push: PushNotifier,
        exec_timeout_s: float = 60.0,
    ) -> None:
        self._store = store
        self._driver = driver
        self._events = events
        self._clock = clock
        self._push = push
        self._exec_timeout_s = exec_timeout_s

    async def run_forever(self, poll_s: float = 30.0) -> None:
        while True:
            try:
                await self.tick()
            except Exception:
                log.exception("scheduler tick failed")
            await asyncio.sleep(poll_s)

    async def tick(self) -> None:
        """One pass: auto-resolve past-deadline worries, then run every due active watcher."""
        for state in ("active", "paused"):
            for data in await self._store.watchers.query(state=state):
                try:
                    watcher = Watcher.model_validate(data)
                    if await self._resolve_if_past_deadline(watcher.id):
                        continue
                    if watcher.state == "active" and await self._is_due(watcher):
                        await self._run_one(watcher)
                except Exception as exc:
                    # Type only: exception text can carry row or watcher-output content.
                    log.error(
                        "watcher run failed",
                        extra={"watcher_id": data.get("id"), "error": type(exc).__name__},
                    )

    # --- scheduling state ---

    async def _entry(self, watcher_id: str) -> _ScheduleEntry:
        data = await self._store.schedule.get(watcher_id)
        if data is None:
            return _ScheduleEntry()
        next_run_at = data["next_run_at"]
        return _ScheduleEntry(
            next_run_at=datetime.fromisoformat(next_run_at) if next_run_at else None,
            consecutive_errors=int(data["consecutive_errors"]),
        )

    async def _put_entry(self, watcher_id: str, entry: _ScheduleEntry) -> None:
        next_run_at = entry.next_run_at.isoformat() if entry.next_run_at else None
        await self._store.schedule.put(
            watcher_id,
            {"next_run_at": next_run_at, "consecutive_errors": entry.consecutive_errors},
        )

    async def _is_due(self, watcher: Watcher) -> bool:
        entry = await self._entry(watcher.id)
        return entry.next_run_at is None or entry.next_run_at <= self._clock.now()

    # --- one run ---

    async def _run_one(self, watcher: Watcher) -> None:
        # Claim the slot before running: whatever happens after this (a crash, a vanished
        # row), the watcher isn't due again for interval_s. No tight re-run loops.
        entry = await self._entry(watcher.id)
        entry.next_run_at = self._clock.now() + timedelta(seconds=watcher.interval_s)
        await self._put_entry(watcher.id, entry)

        result = await self._exec(watcher)

        async with self._store.write_lock:
            await self._apply(watcher.id, result)

    async def _apply(self, watcher_id: str, result: WatchResult) -> None:
        # The person may have let go (or a deadline sweep closed it) while we were waiting.
        current = await self._store.watchers.get(watcher_id)
        if current is None or current["state"] != "active":
            return
        watcher = Watcher.model_validate(current)
        loaded = await self._load_worry(watcher.worry_id)
        if loaded is None:
            return
        worry, timeline = loaded

        now = self._clock.now()
        entry = await self._entry(watcher.id)
        watcher.last_result = result

        if result.status == "error":
            entry.consecutive_errors += 1
            entry.next_run_at = now + timedelta(seconds=watcher.interval_s)
            if entry.consecutive_errors >= ERRORS_BEFORE_PAUSE:
                await self._pause(watcher, worry, timeline, now)
            else:
                await save_watcher(self._store, watcher)
                await self._publish_result(watcher, result)
            await self._put_entry(watcher.id, entry)
            return

        entry.consecutive_errors = 0
        entry.next_run_at = now + timedelta(
            seconds=min(max(result.next_check_s, MIN_NEXT_CHECK_S), MAX_NEXT_CHECK_S)
        )
        await self._put_entry(watcher.id, entry)

        if result.status == "ok":
            await save_watcher(self._store, watcher)
            await self._publish_result(watcher, result)
        elif result.status == "act_now":
            await save_watcher(self._store, watcher)
            await self._publish_result(watcher, result)
            await self._alert(worry, timeline, result, now)
        else:  # resolved
            await self._close(watcher, worry, timeline, now, result.summary, result.fear_came_true)

    async def _exec(self, watcher: Watcher) -> WatchResult:
        try:
            out = await asyncio.wait_for(
                self._driver.exec(watcher.sandbox_name, RUN_COMMAND),
                timeout=self._exec_timeout_s,
            )
        except TimeoutError:
            return self._error_result("The check took too long.")
        except Exception as exc:
            # Type only: a driver error may quote the watcher's stdout/stderr.
            log.warning(
                "sandbox exec failed",
                extra={"watcher_id": watcher.id, "error": type(exc).__name__},
            )
            return self._error_result("The check could not run.")
        if out.exit_code != 0:
            return self._error_result("The check stopped with an error.")
        if len(out.stdout) > MAX_STDOUT_CHARS:
            return self._error_result("The check gave an answer that was far too long.")
        try:
            result = WatchResult.model_validate(json.loads(out.stdout))
        except (ValueError, RecursionError, ValidationError):
            # ValueError covers JSONDecodeError and over-long int literals; RecursionError
            # covers deeply nested input. Log that it happened, never the payload itself.
            log.warning("invalid watcher output", extra={"watcher_id": watcher.id})
            return self._error_result("The check gave an answer I couldn't read.")
        return _bounded(result)

    def _error_result(self, summary: str) -> WatchResult:
        return WatchResult(
            status="error",
            summary=summary,
            evidence=Evidence(source="warden", checked_at=self._clock.now(), data={}),
            fear_came_true=None,
            next_check_s=0,
        )

    # --- outcomes ---

    async def _alert(
        self, worry: Worry, timeline: list[TimelineEvent], result: WatchResult, now: datetime
    ) -> None:
        if worry.status == "needs_you":
            return  # already told them once; don't repeat
        worry.status = "needs_you"
        worry.updated_at = now
        timeline.append(TimelineEvent(at=now, kind="act_now", text=result.summary))
        await save_worry(self._store, worry, timeline)
        await self._events.publish(
            "alert.act_now", {"worry_id": worry.id, "summary": result.summary}
        )
        await self._events.publish("worry.updated", {"worry_id": worry.id})
        await self._push.notify("act_now", worry.id, result.summary)

    async def _pause(
        self, watcher: Watcher, worry: Worry, timeline: list[TimelineEvent], now: datetime
    ) -> None:
        # The sandbox is kept so the failure can be inspected; let-go deletes it.
        watcher.state = "paused"
        await save_watcher(self._store, watcher)
        text = "I couldn't check this 3 times in a row, so I paused it."
        worry.status = "needs_you"
        worry.updated_at = now
        timeline.append(TimelineEvent(at=now, kind="failed", text=text))
        await save_worry(self._store, worry, timeline)
        await self._events.publish("worry.updated", {"worry_id": worry.id})
        await self._push.notify("watcher_paused", worry.id, text)

    async def _resolve_if_past_deadline(self, watcher_id: str) -> bool:
        async with self._store.write_lock:
            current = await self._store.watchers.get(watcher_id)
            if current is None or current["state"] not in ("active", "paused"):
                return True  # closed meanwhile (e.g. let-go): nothing to run either
            watcher = Watcher.model_validate(current)
            loaded = await self._load_worry(watcher.worry_id)
            if loaded is None:
                return False
            worry, timeline = loaded
            now = self._clock.now()
            if worry.deadline is None or worry.deadline > now or worry.status == "resolved":
                return False
            resolution = "The deadline passed, so I stopped watching."
            await self._close(watcher, worry, timeline, now, resolution, None)
            return True

    async def _close(
        self,
        watcher: Watcher,
        worry: Worry,
        timeline: list[TimelineEvent],
        now: datetime,
        resolution: str,
        fear_came_true: bool | None,
    ) -> None:
        try:
            await self._driver.delete(watcher.sandbox_name)
        except KeyError:
            pass  # already gone (e.g. driver state lost across a restart)
        watcher.state = "retired"
        await save_watcher(self._store, watcher)
        await self._store.schedule.delete(watcher.id)

        worry.status = "resolved"
        worry.resolution = resolution
        worry.updated_at = now
        timeline.append(TimelineEvent(at=now, kind="resolved", text=resolution))
        if fear_came_true is not None:
            worry.fear_came_true = fear_came_true
        await save_worry(self._store, worry, timeline)
        await self._events.publish("worry.updated", {"worry_id": worry.id})
        if worry.fear_came_true is None:
            # Asked once, when it closes; the app answers via POST /api/worries/{id}/outcome.
            await self._push.notify("ask_outcome", worry.id, ASK_OUTCOME_TEXT)

    # --- helpers ---

    async def _load_worry(self, worry_id: str) -> tuple[Worry, list[TimelineEvent]] | None:
        row = await self._store.worries.get(worry_id)
        return parse_row(row) if row else None

    async def _publish_result(self, watcher: Watcher, result: WatchResult) -> None:
        # Live status for an open app screen only: not an alert, no push.
        await self._events.publish(
            "watcher.result", {"worry_id": watcher.worry_id, "status": result.status}
        )


def _bounded(result: WatchResult) -> WatchResult:
    """Cap the untrusted evidence before it is stored and served back out."""
    evidence = result.evidence
    data = evidence.data
    if len(json.dumps(data)) > MAX_EVIDENCE_DATA_CHARS:
        data = {"truncated": True}
    bounded = evidence.model_copy(
        update={"source": evidence.source[:MAX_EVIDENCE_SOURCE_CHARS], "data": data}
    )
    return result.model_copy(update={"evidence": bounded})
