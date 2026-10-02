"""The compiler end to end: scripted model answers, a scripted sandbox, a real store."""

import json
from collections.abc import AsyncIterator, Callable
from datetime import UTC, datetime
from pathlib import Path

import aiosqlite
import pytest
from warden.compiler.llm import LLMError, Message, Stage
from warden.compiler.pipeline import (
    MAX_ATTEMPTS,
    PARK_PERSON,
    PARK_WORRY_TIME,
    Compiler,
)
from warden.db import SCHEMA, Store
from warden.events import EventBus
from warden.models import TimelineEvent, Watcher, Worry
from warden.sandbox.driver import ExecResult, SandboxHandle
from warden.worry_rows import parse_row, save_worry

REPLAY = json.loads(
    (Path(__file__).parent.parent / "fixtures" / "llm" / "replay.json").read_text()
)["cases"]
PARCEL, TRAIN, WEATHER, PERSON, SOCIAL = REPLAY
WORRY_ID = "w_01K6B8Z3Q4R5S6T7V8W9XA0001"
NOW = datetime(2026, 10, 1, 9, 0, tzinfo=UTC)
WATCHED_SECRET = "PRIVATE-INBOX-CONTENT"


def ok_run() -> ExecResult:
    body = {
        "status": "ok",
        "summary": "Parcel is on its way.",
        "evidence": {"source": "DHL", "checked_at": NOW.isoformat(), "data": {"x": 1}},
        "fear_came_true": None,
        "next_check_s": 3600,
    }
    return ExecResult(stdout=json.dumps(body), stderr="", exit_code=0)


def crash_run() -> ExecResult:
    return ExecResult(
        stdout=json.dumps({"evidence": WATCHED_SECRET}),
        stderr="  File \"/w/run.py\", line 9, in <module>\nKeyError: 'daily'\n",
        exit_code=1,
    )


class ScriptedLLM:
    def __init__(self, triage: list[str], codegen: list[str]) -> None:
        self.answers: dict[Stage, list[str]] = {"triage": triage, "codegen": codegen}
        self.calls: list[tuple[Stage, list[Message]]] = []
        self.before_codegen: Callable[[], object] | None = None

    async def complete(self, stage: Stage, messages: list[Message]) -> str:
        self.calls.append((stage, list(messages)))
        if stage == "codegen" and self.before_codegen is not None:
            await self.before_codegen()  # type: ignore[misc]
        if not self.answers.setdefault(stage, []):
            raise LLMError(f"{stage}: model endpoint unavailable after retries (HTTP 503)")
        return self.answers[stage].pop(0)


class ScriptedDriver:
    def __init__(self, *runs: ExecResult) -> None:
        self.runs = list(runs)
        self.live: set[str] = set()
        self.created: list[str] = []
        self.policies: dict[str, str] = {}
        self.files: dict[str, dict[str, str]] = {}

    async def create(self, name: str, image: str) -> SandboxHandle:
        self.live.add(name)
        self.created.append(name)
        return SandboxHandle(name=name, status="ready")

    async def apply_policy(self, name: str, policy_yaml: str) -> None:
        self.policies[name] = policy_yaml

    async def write_file(self, name: str, path: str, content: str) -> None:
        self.files.setdefault(name, {})[path] = content

    async def exec(self, name: str, command: list[str]) -> ExecResult:
        assert command == ["python3", "/w/run.py"]
        assert "/w/run.py" in self.files[name]
        return self.runs.pop(0)

    async def delete(self, name: str) -> None:
        self.live.remove(name)

    async def ensure_running(self, name: str) -> bool:
        return name in self.live


@pytest.fixture
async def store(warden_test_environment: str) -> AsyncIterator[Store]:
    async with aiosqlite.connect(warden_test_environment) as conn:
        await conn.executescript(SCHEMA)
        s = Store(conn)
        worry = Worry(
            id=WORRY_ID,
            text="Will my DHL parcel 00340434161094042557 arrive by Friday 16:00?",
            type="unclassified",
            fear="",
            deadline=None,
            status="triaging",
            watcher_id=None,
            resolution=None,
            fear_came_true=None,
            created_at=NOW,
            updated_at=NOW,
        )
        await save_worry(s, worry, [TimelineEvent(at=NOW, kind="created", text="x")])
        yield s


async def load(store: Store) -> tuple[Worry, list[str], Watcher | None]:
    row = await store.worries.get(WORRY_ID)
    assert row is not None
    worry, timeline = parse_row(row)
    watcher = None
    if worry.watcher_id:
        watcher = Watcher.model_validate(await store.watchers.get(worry.watcher_id))
    return worry, [t.kind for t in timeline], watcher


def compiler(store: Store, llm: ScriptedLLM, driver: ScriptedDriver) -> tuple[Compiler, EventBus]:
    bus = EventBus()
    return Compiler(store, bus, driver, llm, clock=lambda: NOW), bus


async def test_happy_path_reaches_awaiting_approval(store: Store) -> None:
    llm = ScriptedLLM([PARCEL["triage"]], [PARCEL["codegen"]])
    driver = ScriptedDriver(ok_run())
    c, bus = compiler(store, llm, driver)
    events = bus.subscribe()

    outcome = await c.compile_worry(WORRY_ID)

    worry, kinds, watcher = await load(store)
    assert outcome.status == "awaiting_approval" and outcome.attempts == 1
    assert worry.status == "awaiting_approval"
    assert (worry.type, worry.deadline) == ("deadline", datetime(2026, 10, 2, 16, tzinfo=UTC))
    assert kinds == ["created", "triaged", "compiled", "approval_requested"]
    assert watcher is not None and watcher.state == "awaiting_approval"
    assert watcher.adapters == ["parcel_dhl"]
    assert [p.host for p in watcher.policy_summary] == ["api-eu.dhl.com"]
    assert watcher.sandbox_name in watcher.policy_yaml
    assert watcher.code.startswith("from watcher_runtime import harness")
    # The dry run used its own throwaway sandbox, the same generated policy shape, and cleaned up.
    (dry,) = driver.created
    assert dry.startswith("cwd-") and driver.live == set()
    assert "api-eu.dhl.com" in driver.policies[dry]
    assert driver.files[dry]["/w/run.py"] == watcher.code
    types = []
    while not events.empty():
        types.append(events.get_nowait().type)
    assert types == ["worry.updated", "worry.updated", "approval.needed"]


async def test_crash_is_fed_back_through_the_guard_and_retry_succeeds(store: Store) -> None:
    llm = ScriptedLLM([PARCEL["triage"]], [PARCEL["codegen"], PARCEL["codegen"]])
    driver = ScriptedDriver(crash_run(), ok_run())
    c, _ = compiler(store, llm, driver)

    outcome = await c.compile_worry(WORRY_ID)

    assert outcome.status == "awaiting_approval" and outcome.attempts == 2
    retry_prompt = [m for s, m in llm.calls if s == "codegen"][1][-1].content
    assert "run.py crashed" in retry_prompt
    assert "Traceback lines in run.py: 9" in retry_prompt
    assert "Exception type: KeyError" in retry_prompt
    assert WATCHED_SECRET not in retry_prompt  # stdout is never echoed to the model
    assert driver.live == set()


async def test_gate_rejection_is_fed_back_without_touching_a_sandbox(store: Store) -> None:
    evil = PARCEL["codegen"].replace(
        "from watcher_runtime import harness",
        "import subprocess\nfrom watcher_runtime import harness",
    )
    llm = ScriptedLLM([PARCEL["triage"]], [evil, PARCEL["codegen"]])
    driver = ScriptedDriver(ok_run())
    c, _ = compiler(store, llm, driver)

    outcome = await c.compile_worry(WORRY_ID)

    assert outcome.status == "awaiting_approval" and outcome.attempts == 2
    assert len(driver.created) == 1  # the rejected code never reached a sandbox
    retry_prompt = [m for s, m in llm.calls if s == "codegen"][1][-1].content
    assert "static checker rejected run.py" in retry_prompt and "subprocess" in retry_prompt


async def test_three_failures_fail_honestly_and_leave_nothing_behind(store: Store) -> None:
    llm = ScriptedLLM([PARCEL["triage"]], [PARCEL["codegen"]] * MAX_ATTEMPTS)
    driver = ScriptedDriver(*[crash_run() for _ in range(MAX_ATTEMPTS)])
    c, _ = compiler(store, llm, driver)

    outcome = await c.compile_worry(WORRY_ID)

    worry, kinds, watcher = await load(store)
    assert outcome.status == "failed" and outcome.attempts == 3
    assert worry.status == "failed"
    assert worry.resolution == (
        "Testing the watcher failed: the check crashed. Nothing was set up; you can try again."
    )
    assert kinds[-1] == "failed"
    # No half-created watcher, no sandbox left: the app shows no jail for it.
    assert watcher is None and worry.watcher_id is None
    assert len(driver.created) == 3 and driver.live == set()


async def test_s7_incident_a_source_that_refuses_is_a_testing_failure(store: Store) -> None:
    # The S7 watcher's stop id didn't exist: BVG answered 404 and run.py reported `error`.
    error = json.loads(ok_run().stdout) | {"status": "error", "summary": "BVG unreachable"}
    err_run = ExecResult(json.dumps(error), "", 0)
    llm = ScriptedLLM([PARCEL["triage"]], [PARCEL["codegen"]] * MAX_ATTEMPTS)
    driver = ScriptedDriver(*[err_run] * MAX_ATTEMPTS)
    c, _ = compiler(store, llm, driver)

    await c.compile_worry(WORRY_ID)

    worry, kinds, watcher = await load(store)
    assert worry.status == "failed"  # not "parked": it could be watched, building failed
    assert worry.resolution is not None
    assert worry.resolution.startswith("Testing the watcher failed: the check could not get")
    assert watcher is None and driver.live == set()


async def test_status_error_on_the_dry_run_is_a_failure(store: Store) -> None:
    error = json.loads(ok_run().stdout) | {"status": "error"}
    err_run = ExecResult(json.dumps(error), "", 0)
    llm = ScriptedLLM([PARCEL["triage"]], [PARCEL["codegen"]] * 2)
    c, _ = compiler(store, llm, ScriptedDriver(err_run, ok_run()))
    assert (await c.compile_worry(WORRY_ID)).attempts == 2


@pytest.mark.parametrize(("case", "reason"), [(PERSON, PARK_PERSON), (SOCIAL, PARK_WORRY_TIME)])
async def test_person_and_social_worries_are_parked_without_codegen(
    store: Store, case: dict[str, str], reason: str
) -> None:
    llm = ScriptedLLM([case["triage"]], [])
    driver = ScriptedDriver()
    c, _ = compiler(store, llm, driver)

    await c.compile_worry(WORRY_ID)

    worry, kinds, watcher = await load(store)
    assert (worry.status, worry.resolution) == ("parked", reason)
    assert kinds == ["created", "triaged", "parked"]
    assert watcher is None and driver.created == []
    assert [s for s, _ in llm.calls] == ["triage"]


async def test_model_outage_fails_naming_the_phase(store: Store) -> None:
    c, _ = compiler(store, ScriptedLLM([], []), ScriptedDriver())
    await c.compile_worry(WORRY_ID)
    worry, kinds, _ = await load(store)
    assert worry.status == "failed"
    assert worry.resolution == (
        "Understanding it failed: the language model gave no usable answer. "
        "Nothing was set up; you can try again."
    )


async def test_let_go_during_compile_is_never_revived(store: Store) -> None:
    llm = ScriptedLLM([PARCEL["triage"]], [PARCEL["codegen"]])
    driver = ScriptedDriver(ok_run())

    async def let_go() -> None:
        async with store.write_lock:
            row = await store.worries.get(WORRY_ID)
            assert row is not None
            worry, timeline = parse_row(row)
            worry.status = "resolved"
            await save_worry(store, worry, timeline)

    llm.before_codegen = let_go
    c, _ = compiler(store, llm, driver)
    await c.compile_worry(WORRY_ID)

    worry, kinds, watcher = await load(store)
    assert worry.status == "resolved" and watcher is None
    assert "approval_requested" not in kinds


async def test_not_triaging_is_left_alone(store: Store) -> None:
    llm = ScriptedLLM([PARCEL["triage"]], [])
    async with store.write_lock:
        row = await store.worries.get(WORRY_ID)
        assert row is not None
        worry, timeline = parse_row(row)
        worry.status = "resolved"
        await save_worry(store, worry, timeline)
    c, _ = compiler(store, llm, ScriptedDriver())
    await c.compile_worry(WORRY_ID)
    assert llm.calls == []


async def test_a_worry_stranded_mid_compile_is_picked_up_again(store: Store) -> None:
    async with store.write_lock:
        row = await store.worries.get(WORRY_ID)
        assert row is not None
        worry, timeline = parse_row(row)
        worry.status = "compiling"  # a restart cancelled the compile here
        await save_worry(store, worry, timeline)
    llm = ScriptedLLM([PARCEL["triage"]], [PARCEL["codegen"]])
    c, _ = compiler(store, llm, ScriptedDriver(ok_run()))

    assert await c.stranded() == [WORRY_ID]
    assert (await c.compile_worry(WORRY_ID)).status == "awaiting_approval"


async def test_missing_input_parks_once_with_an_actionable_reason(store: Store) -> None:
    invented = (
        '```json\n{"adapters": [{"name": "ics_calendar", "params": '
        '{"url": "https://school.example.de/calendar.ics"}}], "interval_s": 3600}\n```\n'
        "```python\nfrom watcher_runtime import harness\nharness.emit('ok', 'x', 'y')\n```"
    )
    llm = ScriptedLLM([PARCEL["triage"]], [invented, PARCEL["codegen"]])
    driver = ScriptedDriver(ok_run())
    c, _ = compiler(store, llm, driver)

    outcome = await c.compile_worry(WORRY_ID)

    worry, kinds, watcher = await load(store)
    assert (worry.status, worry.resolution) == (
        "parked",
        "Send me the link to the calendar and I'll watch it.",
    )
    assert kinds[-1] == "parked"
    assert outcome.attempts == 1  # no retry: it would only invent another URL
    assert [s for s, _ in llm.calls].count("codegen") == 1
    assert watcher is None and driver.created == []  # never reached a sandbox


async def test_bvg_down_is_a_lookup_failure_naming_bvg(
    store: Store, monkeypatch: pytest.MonkeyPatch
) -> None:
    # 2026-10-02, 08:17 Berlin: BVG's /locations answered 503 on every try.
    import httpx2 as httpx
    from warden.adapters import bvg_lookup
    from warden.compiler import codegen

    text = "What if the S7 from Lichtenberg is cancelled at 9:00?"
    row = await store.worries.get(WORRY_ID)
    assert row is not None
    worry, timeline = parse_row(row)
    await save_worry(store, worry.model_copy(update={"text": text}), timeline)
    calls: list[str] = []

    async def down(path: str, params: dict[str, str]) -> object:
        calls.append(path)
        request = httpx.Request("GET", "https://v6.bvg.transport.rest" + path)
        response = httpx.Response(503, request=request)
        raise httpx.HTTPStatusError("503", request=request, response=response)

    async def no_sleep(seconds: float) -> None:
        return None

    monkeypatch.setattr(bvg_lookup, "fetch", down)
    monkeypatch.setattr(bvg_lookup, "sleep", no_sleep)
    plan = {"adapters": [{"name": "transit_bvg", "params": {"stop": "Lichtenberg", "line": "S7"}}],
            "interval_s": 300}  # fmt: skip
    code = (
        "from watcher_runtime import harness\nfrom watcher_runtime.adapters import transit_bvg\n"
        f'STOP_ID = "{codegen.STOP_PLACEHOLDER}"\ndata = transit_bvg.fetch(STOP_ID)\n'
        'harness.emit("ok", "S7 looks normal.", "BVG")\n'
    )
    answer = f"```json\n{json.dumps(plan)}\n```\n```python\n{code}```"
    driver = ScriptedDriver()
    c, _ = compiler(store, ScriptedLLM([TRAIN["triage"]], [answer]), driver)

    await c.compile_worry(WORRY_ID)

    worry, kinds, watcher = await load(store)
    assert worry.status == "failed" and kinds[-1] == "failed"
    assert worry.resolution == (
        "Looking up the stop failed: BVG's public timetable service isn't answering right now."
        " Nothing was set up; you can try again."
    )
    assert len(calls) == 3  # one try + two retries
    assert watcher is None and driver.created == []
