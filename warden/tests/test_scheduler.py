"""T-10 acceptance: simulated-clock tests for the scheduler.

A FakeClock is advanced by hand and a FakeDriver replays scripted watcher stdouts,
so nothing sleeps and nothing touches a real sandbox or the network.
"""

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from typing import Any

import aiosqlite
import pytest
from warden.db import SCHEMA, Store
from warden.events import EventBus
from warden.models import Event, TimelineEvent, Watcher, Worry
from warden.sandbox.driver import ExecResult, SandboxHandle
from warden.scheduler import PushKind, Scheduler
from warden.worry_rows import parse_row, save_watcher, save_worry

WORRY_ID = "w_01K6B8Z3Q4R5S6T7V8W9XA0001"
WATCHER_ID = "wt_01K6B8Z3Q4R5S6T7V8W9XA0002"
SANDBOX = "cw-xa0001"
START = datetime(2026, 9, 30, 8, 0, tzinfo=UTC)
HOUR = timedelta(hours=1)

HANG = object()  # scripted step: exec never returns (exercises the timeout)


class FakeClock:
    def __init__(self, now: datetime) -> None:
        self._now = now

    def now(self) -> datetime:
        return self._now

    def advance(self, delta: timedelta) -> None:
        self._now += delta


class FakeDriver:
    """Replays one scripted step per exec: an ExecResult, an exception, or HANG."""

    def __init__(self) -> None:
        self.script: list[object] = []
        self.execs: list[str] = []
        self.deleted: list[str] = []
        self.on_exec: Any = None
        self.present = True  # what ensure_running finds after a "reboot"
        self.calls: list[tuple[str, str, str]] = []  # (op, name, payload) for reconcile tests

    async def create(self, name: str, image: str) -> SandboxHandle:
        self.calls.append(("create", name, image))
        return SandboxHandle(name=name, status="ready")

    async def apply_policy(self, name: str, policy_yaml: str) -> None:
        self.calls.append(("apply_policy", name, policy_yaml))

    async def write_file(self, name: str, path: str, content: str) -> None:
        self.calls.append(("write_file", name, f"{path}:{content}"))

    async def ensure_running(self, name: str) -> bool:
        self.calls.append(("ensure_running", name, ""))
        return self.present

    async def exec(self, name: str, command: list[str]) -> ExecResult:
        self.execs.append(name)
        step = self.script.pop(0)
        if self.on_exec is not None:
            await self.on_exec()
        if step is HANG:
            await asyncio.sleep(3600)
        if isinstance(step, BaseException):
            raise step
        assert isinstance(step, ExecResult)
        return step

    async def delete(self, name: str) -> None:
        self.deleted.append(name)


class FakePush:
    def __init__(self) -> None:
        self.sent: list[tuple[PushKind, str]] = []

    async def notify(self, kind: PushKind, worry_id: str, text: str) -> None:
        self.sent.append((kind, worry_id))


def result(status: str, next_check_s: int = 3600, **extra: Any) -> ExecResult:
    body = {
        "status": status,
        "summary": f"watcher says {status}",
        "evidence": {"source": "DHL", "checked_at": "2026-09-30T08:00:00Z", "data": {}},
        "fear_came_true": None,
        "next_check_s": next_check_s,
        **extra,
    }
    return ExecResult(stdout=json.dumps(body), stderr="", exit_code=0)


class Harness:
    def __init__(self, store: Store) -> None:
        self.store = store
        self.clock = FakeClock(START)
        self.driver = FakeDriver()
        self.push = FakePush()
        self.bus = EventBus()
        self.events = self.bus.subscribe()
        self.scheduler = Scheduler(
            store, self.driver, self.bus, self.clock, self.push, exec_timeout_s=0.05
        )

    async def seed(self, deadline: datetime | None = None) -> None:
        worry = Worry(
            id=WORRY_ID,
            text="I'm worried my parcel won't arrive before Friday",
            type="deadline",
            fear="Parcel not delivered by Friday 18:00",
            deadline=deadline,
            status="watching",
            watcher_id=WATCHER_ID,
            resolution=None,
            fear_came_true=None,
            created_at=START,
            updated_at=START,
        )
        await save_worry(self.store, worry, [])
        watcher = Watcher(
            id=WATCHER_ID,
            worry_id=WORRY_ID,
            adapters=["parcel_dhl"],
            code="",
            policy_yaml="network_policies: {}\n",
            policy_summary=[],
            sandbox_name=SANDBOX,
            interval_s=3600,
            state="active",
            last_result=None,
        )
        await save_watcher(self.store, watcher)

    async def run(self, *steps: object, every: timedelta = HOUR) -> None:
        """One tick per scripted step, advancing the clock between ticks."""
        for step in steps:
            self.driver.script.append(step)
            await self.scheduler.tick()
            self.clock.advance(every)

    async def worry(self) -> tuple[Worry, list[str]]:
        row = await self.store.worries.get(WORRY_ID)
        assert row is not None
        worry, timeline = parse_row(row)
        return worry, [t.kind for t in timeline]

    async def watcher(self) -> Watcher:
        return Watcher.model_validate(await self.store.watchers.get(WATCHER_ID))

    def drained(self) -> list[Event]:
        out = []
        while not self.events.empty():
            out.append(self.events.get_nowait())
        return out


@pytest.fixture
async def h(warden_test_environment: str) -> AsyncIterator[Harness]:
    async with aiosqlite.connect(warden_test_environment) as conn:
        await conn.executescript(SCHEMA)
        harness = Harness(Store(conn))
        await harness.seed()
        yield harness


async def test_silence_while_ok(h: Harness) -> None:
    await h.run(*[result("ok") for _ in range(10)])

    assert len(h.driver.execs) == 10
    assert h.push.sent == []
    events = h.drained()
    assert {e.type for e in events} == {"watcher.result"}
    worry, timeline = await h.worry()
    assert worry.status == "watching"
    assert timeline == []  # no noise in the timeline either
    assert (await h.watcher()).last_result is not None


async def test_not_due_means_no_exec_and_next_check_is_clamped(h: Harness) -> None:
    # The watcher asks to be re-run after 1 s; the scheduler holds it to 300 s.
    h.driver.script.append(result("ok", next_check_s=1))
    await h.scheduler.tick()
    h.clock.advance(timedelta(seconds=299))
    await h.scheduler.tick()
    assert len(h.driver.execs) == 1

    h.clock.advance(timedelta(seconds=1))
    h.driver.script.append(result("ok"))
    await h.scheduler.tick()
    assert len(h.driver.execs) == 2


async def test_act_now_alerts_exactly_once(h: Harness) -> None:
    await h.run(result("ok"), result("act_now"), result("act_now"), result("act_now"))

    assert h.push.sent == [("act_now", WORRY_ID)]
    alerts = [e for e in h.drained() if e.type == "alert.act_now"]
    assert len(alerts) == 1
    assert alerts[0].data == {"worry_id": WORRY_ID, "summary": "watcher says act_now"}
    worry, timeline = await h.worry()
    assert worry.status == "needs_you"
    assert timeline == ["act_now"]
    assert (await h.watcher()).state == "active"  # keeps watching so it can still resolve


async def test_three_errors_in_a_row_pause_and_notify_once(h: Harness) -> None:
    await h.run(
        ExecResult(stdout="not json", stderr="", exit_code=0),
        ExecResult(stdout=json.dumps({"summary": "no status"}), stderr="", exit_code=0),
        ExecResult(stdout="", stderr="boom", exit_code=1),
    )

    watcher = await h.watcher()
    assert watcher.state == "paused"
    assert watcher.last_result is not None and watcher.last_result.status == "error"
    assert h.push.sent == [("watcher_paused", WORRY_ID)]
    worry, timeline = await h.worry()
    assert worry.status == "needs_you"
    assert timeline == ["failed"]
    assert h.driver.deleted == []  # sandbox kept for inspection
    assert await h.store.sandboxes_live() == 1  # ...so it still counts (health + ledger)

    # Never scheduled again, so never notified again.
    for _ in range(5):
        await h.scheduler.tick()
        h.clock.advance(HOUR)
    assert len(h.driver.execs) == 3
    assert h.push.sent == [("watcher_paused", WORRY_ID)]


async def test_errors_must_be_consecutive(h: Harness) -> None:
    bad = ExecResult(stdout="{", stderr="", exit_code=0)
    await h.run(bad, bad, result("ok"), bad, bad)

    assert (await h.watcher()).state == "active"
    assert h.push.sent == []


async def test_exec_timeout_and_driver_failure_count_as_errors(h: Harness) -> None:
    await h.run(HANG, RuntimeError("sandbox gone"), HANG)

    assert (await h.watcher()).state == "paused"
    assert h.push.sent == [("watcher_paused", WORRY_ID)]


async def test_resolved_closes_and_asks_did_it_happen(h: Harness) -> None:
    await h.run(result("ok"), result("resolved"))

    worry, timeline = await h.worry()
    assert worry.status == "resolved"
    assert worry.resolution == "watcher says resolved"
    assert worry.fear_came_true is None
    assert timeline == ["resolved"]
    assert (await h.watcher()).state == "retired"
    assert h.driver.deleted == [SANDBOX]
    assert h.push.sent == [("ask_outcome", WORRY_ID)]

    await h.run(*[result("ok")])  # a retired watcher is never run again
    assert len(h.driver.execs) == 2


async def test_resolved_with_known_outcome_does_not_ask(h: Harness) -> None:
    await h.run(result("resolved", fear_came_true=False))

    worry, _ = await h.worry()
    assert worry.status == "resolved"
    assert worry.fear_came_true is False
    assert h.push.sent == []


async def test_deadline_auto_resolves_without_running(h: Harness) -> None:
    await h.seed(deadline=START + 2 * HOUR)
    await h.run(result("ok"), result("ok"))  # runs at 08:00 and 09:00
    assert len(h.driver.execs) == 2

    await h.scheduler.tick()  # 10:00: deadline reached
    assert len(h.driver.execs) == 2
    worry, timeline = await h.worry()
    assert worry.status == "resolved"
    assert worry.resolution == "The deadline passed, so I stopped watching."
    assert timeline == ["resolved"]
    assert (await h.watcher()).state == "retired"
    assert h.driver.deleted == [SANDBOX]
    assert h.push.sent == [("ask_outcome", WORRY_ID)]


async def test_deadline_also_closes_a_paused_watcher(h: Harness) -> None:
    await h.seed(deadline=START + 5 * HOUR)
    bad = ExecResult(stdout="", stderr="", exit_code=1)
    await h.run(bad, bad, bad)
    assert (await h.watcher()).state == "paused"

    h.clock.advance(5 * HOUR)
    await h.scheduler.tick()
    worry, timeline = await h.worry()
    assert worry.status == "resolved"
    assert timeline == ["failed", "resolved"]
    assert h.driver.deleted == [SANDBOX]


async def test_let_go_during_exec_discards_the_result(h: Harness) -> None:
    async def let_go() -> None:
        watcher = await h.watcher()
        watcher.state = "retired"
        await save_watcher(h.store, watcher)

    h.driver.on_exec = let_go
    await h.run(result("act_now"))

    assert h.push.sent == []
    assert (await h.watcher()).last_result is None
    worry, _ = await h.worry()
    assert worry.status == "watching"


async def test_scheduler_run_cannot_interleave_with_a_route(
    h: Harness, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A genuine race, not the stale-state check above: while the scheduler
    holds store.write_lock applying a result, a concurrent let-go must wait
    for it. Proves write_lock actually serializes the scheduler against the
    routes (not only against itself) -- remove the lock and this fails.
    """
    interleaved = False
    raced = False
    race_tasks: list[asyncio.Task[None]] = []
    real_put = h.store.watchers.put

    async def concurrent_let_go() -> None:
        # Mirrors routers.worries.let_go_worry's core, without the FastAPI plumbing.
        async with h.store.write_lock:
            row = await h.store.worries.get(WORRY_ID)
            assert row is not None
            worry, timeline = parse_row(row)
            worry.status = "resolved"
            timeline.append(
                TimelineEvent(at=worry.updated_at, kind="let_go", text="You let it go.")
            )
            watcher_data = await h.store.watchers.get(WATCHER_ID)
            assert watcher_data is not None
            watcher = Watcher.model_validate(watcher_data)
            watcher.state = "retired"
            await save_watcher(h.store, watcher)
            await save_worry(h.store, worry, timeline)

    async def put_then_race(*args: Any, **kwargs: Any) -> None:
        nonlocal interleaved, raced
        if raced:
            await real_put(*args, **kwargs)
            return
        raced = True
        race_tasks.append(asyncio.create_task(concurrent_let_go()))
        await asyncio.sleep(0.05)  # give the let-go every chance to interleave
        interleaved = race_tasks[0].done()  # True only if write_lock failed to block it
        await real_put(*args, **kwargs)
        # Not awaited here: this call is still inside the scheduler's own
        # `async with store.write_lock`, and concurrent_let_go() needs that
        # same lock -- awaiting it here would deadlock. It completes once
        # this call returns and that lock is released.

    monkeypatch.setattr(h.store.watchers, "put", put_then_race)
    await h.run(result("ok"))
    await race_tasks[0]

    assert interleaved is False
    worry, _ = await h.worry()
    assert worry.status == "resolved"
    assert (await h.watcher()).state == "retired"


async def test_hostile_output_counts_as_error_not_a_crash(h: Harness) -> None:
    # Deep nesting (RecursionError), an over-long int (ValueError), an oversized payload.
    nested = ExecResult(stdout="[" * 200_000, stderr="", exit_code=0)
    huge_int = ExecResult(
        stdout=result("ok").stdout.replace('"next_check_s": 3600', '"next_check_s": ' + "1" * 5000),
        stderr="",
        exit_code=0,
    )
    too_long = ExecResult(stdout=" " * (64 * 1024 + 1), stderr="", exit_code=0)
    await h.run(nested, huge_int, too_long)

    assert (await h.watcher()).state == "paused"
    assert h.push.sent == [("watcher_paused", WORRY_ID)]


async def test_a_failing_run_is_not_retried_before_interval(h: Harness) -> None:
    # The worry row vanishes, so the run can't be applied; the slot is still claimed.
    await h.store.worries.delete(WORRY_ID)
    h.driver.script.append(result("ok"))
    await h.scheduler.tick()
    for _ in range(10):
        h.clock.advance(timedelta(seconds=30))
        await h.scheduler.tick()
    assert len(h.driver.execs) == 1


async def test_evidence_is_bounded_before_it_is_stored(h: Harness) -> None:
    big = result(
        "ok",
        evidence={
            "source": "S" * 500,
            "checked_at": "2026-09-30T08:00:00Z",
            "data": {"body": "x" * 10_000},
        },
    )
    await h.run(big)

    last = (await h.watcher()).last_result
    assert last is not None
    assert len(last.evidence.source) == 64
    assert last.evidence.data == {"truncated": True}


# --- T-20: recovery after a reboot -------------------------------------------------------


async def test_reconcile_restarts_a_stopped_sandbox_without_rebuilding_it(h: Harness) -> None:
    await h.scheduler.reconcile()
    assert h.driver.calls == [("ensure_running", SANDBOX, "")]


async def test_reconcile_recreates_a_missing_sandbox_from_the_approved_policy(h: Harness) -> None:
    h.driver.present = False
    await h.scheduler.reconcile()
    watcher = await h.watcher()
    assert h.driver.calls == [
        ("ensure_running", SANDBOX, ""),
        ("create", SANDBOX, "watcher-base"),
        ("apply_policy", SANDBOX, watcher.policy_yaml),
        ("write_file", SANDBOX, f"/w/run.py:{watcher.code}"),
    ]


async def test_reconcile_leaves_retired_watchers_alone(h: Harness) -> None:
    watcher = await h.watcher()
    watcher.state = "retired"
    await save_watcher(h.store, watcher)
    await h.scheduler.reconcile()
    assert h.driver.calls == []


async def test_every_run_restores_the_approved_code_first(h: Harness) -> None:
    await h.run(result("ok"))
    assert ("write_file", SANDBOX, "/w/run.py:") in h.driver.calls
