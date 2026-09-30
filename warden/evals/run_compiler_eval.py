"""`make eval-compiler`: the T-09 acceptance run against the live NVIDIA Build endpoint.

Opt-in and never part of `make test`. Each labelled worry goes through the real
compiler (triage → codegen → static gate → generated policy → dry run) with
CUSTODY_SANDBOX=mock. A case passes when its route is right and, for `watch`
cases, it reached `awaiting_approval`. Exit code 1 below PASS_MARK.

Honest limit: until T-04's OpenShell driver exists, the dry run's exec step is the
mock sandbox, so generated code is gated and policy-checked but not executed here
(running model-written code on the host would break AGENTS invariant #1).

--record saves every model answer to warden/tests/fixtures/llm/recorded/<id>.json.
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import aiosqlite
import yaml
from warden.compiler.llm import LLMClient, Message, NvidiaClient, Stage
from warden.compiler.pipeline import CompileOutcome, Compiler
from warden.db import SCHEMA, Store
from warden.events import EventBus
from warden.ids import new_worry_id
from warden.models import TimelineEvent, Worry
from warden.sandbox.mock import MockDriver
from warden.worry_rows import parse_row, save_worry

PASS_MARK = 8
HERE = Path(__file__).parent
CASES = HERE / "compiler_worries.yaml"
RECORD_DIR = HERE.parent / "tests" / "fixtures" / "llm" / "recorded"


class Recorder:
    def __init__(self, inner: LLMClient) -> None:
        self.inner = inner
        self.answers: list[dict[str, str]] = []

    async def complete(self, stage: Stage, messages: list[Message]) -> str:
        answer = await self.inner.complete(stage, messages)
        self.answers.append({"stage": stage, "content": answer})
        return answer


async def run_case(
    case: dict[str, Any], llm: LLMClient, db_path: str
) -> tuple[CompileOutcome, Worry]:
    async with aiosqlite.connect(db_path) as conn:
        await conn.executescript(SCHEMA)
        store = Store(conn)
        now = datetime.now(UTC)
        worry = Worry(
            id=new_worry_id(),
            text=case["text"],
            type="unclassified",
            fear="",
            deadline=None,
            status="triaging",
            watcher_id=None,
            resolution=None,
            fear_came_true=None,
            created_at=now,
            updated_at=now,
        )
        await save_worry(store, worry, [TimelineEvent(at=now, kind="created", text="eval")])
        outcome = await Compiler(store, EventBus(), MockDriver(), llm).compile_worry(worry.id)
        row = await store.worries.get(worry.id)
        assert row is not None
        return outcome, parse_row(row)[0]


def passed(case: dict[str, Any], outcome: CompileOutcome) -> bool:
    if outcome.route != case["route"]:
        return False
    if case["route"] == "watch":
        return outcome.status == "awaiting_approval"
    return outcome.status == "parked"


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--record", action="store_true")
    parser.add_argument("--only", help="run one case id")
    parser.add_argument("--verbose", action="store_true", help="print every model call")
    args = parser.parse_args()

    if os.environ.get("CUSTODY_SANDBOX") != "mock":
        print("eval-compiler runs with CUSTODY_SANDBOX=mock only", file=sys.stderr)
        return 2
    if not os.environ.get("NVIDIA_API_KEY"):
        print("NVIDIA_API_KEY is not set (put it in .env)", file=sys.stderr)
        return 2

    cases: list[dict[str, Any]] = yaml.safe_load(CASES.read_text())
    if args.only:
        cases = [c for c in cases if c["id"] == args.only]
    score = 0
    print(
        f"{'case':<16} {'want':<7} {'got':<7} {'status':<18} {'try':>3} {'adapters':<22} {'s':>5}"
    )
    with tempfile.TemporaryDirectory() as tmp:
        for i, case in enumerate(cases):
            # Cases run one at a time (no concurrency) so rate limits can't cascade; a fresh
            # client per case keeps its call diagnostics separate.
            client = NvidiaClient.from_env()
            recorder = Recorder(client)
            started = time.monotonic()
            outcome, worry = await run_case(case, recorder, f"{tmp}/eval-{i}.db")
            ok = passed(case, outcome)
            score += ok
            adapters = ",".join(outcome.adapters) or "-"
            if case.get("adapter") and outcome.adapters and case["adapter"] not in outcome.adapters:
                adapters += " (!)"
            print(
                f"{case['id']:<16} {case['route']:<7} {outcome.route or '-':<7} "
                f"{outcome.status or '-':<18} {outcome.attempts:>3} {adapters:<22} "
                f"{time.monotonic() - started:>5.0f}  {'PASS' if ok else 'FAIL'}"
            )
            for problem in outcome.problems:
                print(f"{'':<16} problem: {problem[:300]}")
            if not ok or args.verbose:
                for call in client.calls:  # status, outcome, finish_reason, latency; never the key
                    print(f"{'':<16} call: {call.line()}")
            elif any(c.stage == "triage_fallback" for c in client.calls):
                print(f"{'':<16} note: triage needed the fallback model")
            if args.record:
                RECORD_DIR.mkdir(parents=True, exist_ok=True)
                (RECORD_DIR / f"{case['id']}.json").write_text(
                    json.dumps(
                        {"text": case["text"], "fear": worry.fear, "answers": recorder.answers},
                        indent=2,
                    )
                    + "\n"
                )
    total = len(cases)
    print(f"\n{score}/{total} routed correctly and passed their dry run (need {PASS_MARK}/10)")
    if total < 10:  # a subset (--only): every case must pass
        return 0 if score == total else 1
    return 0 if score >= PASS_MARK else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
