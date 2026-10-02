"""The worry compiler (T-09, DESIGN §4): triage → route → codegen → policy → gate → dry run.

Runs as a background task per new worry. LLM calls and dry runs happen outside
`store.write_lock`; every state change is a check-then-save under it, so a worry
the person let go meanwhile is never revived. A failed attempt goes back to the
model once more (at most 2 retries) with a reason that passed through the
injection guard; after that the worry is parked with an honest reason.
Timeline texts are our own words, never model output or watched content.
"""

import logging
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from warden.adapters import bvg_lookup
from warden.adapters.base import Adapter
from warden.compiler import codegen, gate, guard, hosts
from warden.compiler.dryrun import dry_run
from warden.compiler.llm import LLMClient, LLMError
from warden.compiler.policy import generate_policy
from warden.compiler.triage import Triage, triage
from warden.db import Store
from warden.events import EventBus
from warden.ids import new_watcher_id
from warden.models import TimelineEvent, Watcher, Worry, WorryStatus
from warden.sandbox.driver import SandboxDriver
from warden.worry_rows import parse_row, save_watcher, save_worry

log = logging.getLogger(__name__)

MAX_ATTEMPTS = 3  # the first try + 2 retries with the error fed back

PARK_PERSON = "About a person: I'll offer a private check-in once reassurance is set up."
PARK_WORRY_TIME = "Not something a watcher can settle, so I saved it for your weekly worry time."

# A build failure is not a parked worry (S7 incident): the worry could be watched, building
# its watcher failed. It ends `failed`, with one plain sentence naming the phase that failed,
# nothing set up (no watcher row, no sandbox), a retry offered, and it isn't counted in the
# ledger. Our words only; never model output or watched content.
FAIL_DRY_RUN_DETAIL = {
    "run.py took longer": "the check took longer than a minute",
    "the sandbox could not run": "its sandbox could not run it",
    "run.py crashed": "the check crashed",
    "run.py did not print": "the check gave no answer I could read",
    "run.py reported that its check failed": "the check could not get its data",
}


def failure_sentence(phase: str, detail: str = "") -> str:
    sentences = {
        "understanding": "Understanding it failed: the language model gave no usable answer.",
        "writing": "Writing the watcher failed: no version passed my safety checks.",
        "lookup": (
            "Looking up the stop failed: BVG's public timetable service isn't answering right now."
        ),
        "testing": f"Testing the watcher failed: {detail or 'the test run did not pass'}.",
    }
    return (
        sentences.get(phase, "Setting it up failed because something broke on my side.")
        + " Nothing was set up; you can try again."
    )


@dataclass
class CompileOutcome:
    """What happened, for logs and the eval. Never includes code or model text."""

    route: str = ""
    status: WorryStatus | None = None
    attempts: int = 0
    problems: list[str] = field(default_factory=list)
    adapters: list[str] = field(default_factory=list)
    phase: str = "understanding"  # where a failure would have happened
    detail: str = ""  # the last dry-run failure, in our words


@dataclass
class _Attempt:
    adapters: list[Adapter]
    code: str
    interval_s: int


class Compiler:
    def __init__(
        self,
        store: Store,
        events: EventBus,
        driver: SandboxDriver,
        llm: LLMClient,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        self._store = store
        self._events = events
        self._driver = driver
        self._llm = llm
        self._clock = clock

    async def stranded(self) -> list[str]:
        """Worries a restart interrupted mid-compile, reset to `triaging` so they compile again."""
        ids: list[str] = []
        async with self._store.write_lock:
            for status in ("triaging", "compiling"):
                for row in await self._store.worries.query(status=status):
                    worry, timeline = parse_row(row)
                    if worry.status == "compiling":
                        worry.status = "triaging"
                        await save_worry(self._store, worry, timeline)
                    ids.append(worry.id)
        return ids

    async def compile_worry(self, worry_id: str) -> CompileOutcome:
        outcome = CompileOutcome()
        try:
            await self._compile(worry_id, outcome)
        except LLMError as exc:
            # str(exc) and the call diagnostics are ours: statuses, finish reasons, sizes.
            log.warning(
                "compiler: no usable model answer",
                extra={
                    "worry_id": worry_id,
                    "error": str(exc),
                    "calls": [c.line() for c in exc.calls],
                },
            )
            outcome.problems.append(str(exc))
            phase = outcome.phase if outcome.phase == "understanding" else "writing_model"
            await self._fail(worry_id, outcome, phase)
        except Exception as exc:
            log.exception(
                "compiler crashed", extra={"worry_id": worry_id, "error": type(exc).__name__}
            )
            outcome.problems.append(type(exc).__name__)
            await self._fail(worry_id, outcome, "broken")
        return outcome

    async def _compile(self, worry_id: str, outcome: CompileOutcome) -> None:
        loaded = await self._load(worry_id)
        if loaded is None or loaded[0].status != "triaging":
            return
        text = loaded[0].text

        t = await triage(self._llm, text, self._clock())
        outcome.route = t.route
        if not await self._save_triage(worry_id, t):
            return
        if t.route == "person":
            await self._park(worry_id, ("compiling",), PARK_PERSON, outcome)
            return
        if t.route == "park":
            await self._park(worry_id, ("compiling",), PARK_WORRY_TIME, outcome)
            return

        outcome.phase = "writing"
        messages = codegen.first_messages(text, t, self._clock())
        for attempt in range(1, MAX_ATTEMPTS + 1):
            outcome.attempts = attempt
            if not await self._still(worry_id, "compiling"):
                return  # let go meanwhile; stop spending model calls
            answer = await self._llm.complete("codegen", messages)
            try:
                feedback, candidate = await self._try(answer, text, outcome)
            except bvg_lookup.StopLookupError:
                await self._fail(worry_id, outcome, "lookup")
                return
            except codegen.MissingInput as missing:
                # A URL or identifier the worry doesn't contain: retrying would only invent one.
                outcome.problems.append(f"missing input for {missing.adapter}")
                await self._park(worry_id, ("compiling",), missing.reason, outcome)
                return
            if feedback is None:
                assert candidate is not None
                outcome.adapters = [a.name for a in candidate.adapters]
                await self._await_approval(worry_id, candidate, outcome)
                return
            outcome.problems.append(_headline(feedback))
            messages = codegen.retry_messages(messages, answer, feedback)

        await self._fail(worry_id, outcome, outcome.phase, outcome.detail)

    async def _try(
        self, answer: str, worry_text: str, outcome: CompileOutcome
    ) -> tuple[str | None, _Attempt | None]:
        """(None, attempt) on success, else (feedback for the model, attempt-or-None).

        Raises codegen.MissingInput when the worry lacks what the watcher needs.
        """
        # Stop names → real BVG ids, looked up now; never ids from the model's memory.
        stop_ids: dict[tuple[str, str | None], str] = {}
        for stop, line in codegen.stop_queries(answer, worry_text):
            found = await bvg_lookup.find_stop(stop, line)
            if found is not None:
                stop_ids[(stop, line)] = found.id
        try:
            built = codegen.build(answer, worry_text, stop_ids)
        except codegen.CodegenError as exc:
            # Our message, but it can quote model-chosen names and URLs: wrap it.
            return "Problem:\n" + guard.untrusted(str(exc), "checker", max_chars=500), None
        candidate = _Attempt(built.adapters, built.code, built.interval_s)
        try:
            endpoints = [e for a in built.adapters for e in a.endpoints]
            gate.check(built.code, [a.name for a in built.adapters], endpoints)
        except gate.GateError as exc:
            listing = "\n".join(f"- {p}" for p in exc.problems[:10])
            return (
                "Problem: the static checker rejected run.py:\n"
                + guard.untrusted(listing, "checker", max_chars=1500),
                candidate,
            )
        problem = await hosts.non_public_host((e.host, e.port) for e in endpoints)
        if problem is not None:
            return "Problem:\n" + guard.untrusted(problem, "checker", max_chars=300), candidate
        outcome.phase = "testing"
        result = await dry_run(self._driver, built.adapters, built.code)
        if not result.ok:
            outcome.detail = next(
                (v for k, v in FAIL_DRY_RUN_DETAIL.items() if result.problem.startswith(k)), ""
            )
            return guard.dry_run_feedback(result.exec_result, result.problem), candidate
        return None, candidate

    # --- state changes (each a check-then-save under the store-wide lock) ---

    async def _load(self, worry_id: str) -> tuple[Worry, list[TimelineEvent]] | None:
        row = await self._store.worries.get(worry_id)
        return parse_row(row) if row else None

    async def _still(self, worry_id: str, status: WorryStatus) -> bool:
        loaded = await self._load(worry_id)
        return loaded is not None and loaded[0].status == status

    async def _save_triage(self, worry_id: str, t: Triage) -> bool:
        async with self._store.write_lock:
            loaded = await self._load(worry_id)
            if loaded is None or loaded[0].status != "triaging":
                return False
            worry, timeline = loaded
            now = self._clock()
            worry.type = t.type
            worry.fear = t.fear
            worry.deadline = t.deadline
            worry.status = "compiling"
            worry.updated_at = now
            timeline.append(TimelineEvent(at=now, kind="triaged", text="Understood what to watch."))
            await save_worry(self._store, worry, timeline)
        await self._events.publish("worry.updated", {"worry_id": worry_id})
        return True

    async def _await_approval(
        self, worry_id: str, attempt: _Attempt, outcome: CompileOutcome
    ) -> None:
        async with self._store.write_lock:
            loaded = await self._load(worry_id)
            if loaded is None or loaded[0].status != "compiling":
                return
            worry, timeline = loaded
            watcher = self._watcher(worry.id, attempt, "awaiting_approval")
            await save_watcher(self._store, watcher)
            now = self._clock()
            worry.watcher_id = watcher.id
            worry.status = "awaiting_approval"
            worry.updated_at = now
            timeline.append(
                TimelineEvent(at=now, kind="compiled", text="Wrote a watcher and tested it once.")
            )
            timeline.append(
                TimelineEvent(at=now, kind="approval_requested", text="Asked for your permission.")
            )
            await save_worry(self._store, worry, timeline)
            outcome.status = "awaiting_approval"
        await self._events.publish("worry.updated", {"worry_id": worry_id})
        await self._events.publish("approval.needed", {"worry_id": worry_id})

    async def _fail(
        self, worry_id: str, outcome: CompileOutcome, phase: str, detail: str = ""
    ) -> None:
        """A build failure: `failed`, the phase in one sentence, no watcher saved."""
        if phase == "writing_model":
            reason = failure_sentence("writing").replace(
                "no version passed my safety checks", "the language model gave no usable answer"
            )
        else:
            reason = failure_sentence(phase, detail)
        async with self._store.write_lock:
            loaded = await self._load(worry_id)
            if loaded is None or loaded[0].status not in ("triaging", "compiling"):
                return
            worry, timeline = loaded
            now = self._clock()
            worry.status = "failed"
            worry.resolution = reason
            worry.updated_at = now
            timeline.append(TimelineEvent(at=now, kind="failed", text=reason[:140]))
            await save_worry(self._store, worry, timeline)
            outcome.status = "failed"
        log.warning(
            "compile failed",
            extra={"worry_id": worry_id, "phase": phase, "problems": outcome.problems[-3:]},
        )
        await self._events.publish("worry.updated", {"worry_id": worry_id})

    async def _park(
        self,
        worry_id: str,
        from_statuses: tuple[WorryStatus, ...],
        reason: str,
        outcome: CompileOutcome,
    ) -> None:
        async with self._store.write_lock:
            loaded = await self._load(worry_id)
            if loaded is None or loaded[0].status not in from_statuses:
                return
            worry, timeline = loaded
            now = self._clock()
            worry.status = "parked"
            worry.resolution = reason
            worry.updated_at = now
            timeline.append(TimelineEvent(at=now, kind="parked", text=reason))
            await save_worry(self._store, worry, timeline)
            outcome.status = "parked"
        await self._events.publish("worry.updated", {"worry_id": worry_id})

    def _watcher(self, worry_id: str, attempt: _Attempt, state: str) -> Watcher:
        watcher_id = new_watcher_id()
        sandbox_name = f"cw-{watcher_id[-8:].lower()}"
        policy_yaml, summary = generate_policy(attempt.adapters, sandbox_name)
        return Watcher.model_validate(
            {
                "id": watcher_id,
                "worry_id": worry_id,
                "adapters": [a.name for a in attempt.adapters],
                "code": attempt.code,
                "policy_yaml": policy_yaml,
                "policy_summary": [s.model_dump() for s in summary],
                "sandbox_name": sandbox_name,
                "interval_s": attempt.interval_s,
                "state": state,
                "last_result": None,
            }
        )


def _headline(feedback: str) -> str:
    """The first informative line of a feedback message, for logs and the eval table."""
    for line in feedback.splitlines():
        text = line.strip().lstrip("- ")
        if text and not text.startswith("<") and text != "Problem:":
            return text[:200]
    return "unknown problem"
