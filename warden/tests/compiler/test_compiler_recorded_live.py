"""Replays real NVIDIA Build answers from `make eval-compiler ARGS=--record` (no network).

Each recorded triage must still parse to the case's labelled route, and each watch
case's last code-generation answer must still build and pass the static gate.
school_calendar's percent-encoded Google ICS path used to be rejected (PLAN.md T-09);
since T-04 it is declared in OpenShell's canonical form (ADR-0001) and passes.
"""

import json
from pathlib import Path

import pytest
import yaml
from warden.compiler import gate
from warden.compiler.codegen import build
from warden.compiler.triage import parse_triage

ROOT = Path(__file__).parent.parent
RECORDED = ROOT / "fixtures" / "llm" / "recorded"
CASES = {
    c["id"]: c
    for c in yaml.safe_load((ROOT.parent / "evals" / "compiler_worries.yaml").read_text())
}
IDS = sorted(p.stem for p in RECORDED.glob("*.json"))


def load(case_id: str) -> dict:  # type: ignore[type-arg]
    return json.loads((RECORDED / f"{case_id}.json").read_text())  # type: ignore[no-any-return]


def test_all_ten_cases_are_recorded() -> None:
    assert IDS == sorted(CASES)


@pytest.mark.parametrize("case_id", IDS)
def test_recorded_triage_routes_as_labelled(case_id: str) -> None:
    triages = [a["content"] for a in load(case_id)["answers"] if a["stage"].startswith("triage")]
    assert parse_triage(triages[-1]).route == CASES[case_id]["route"]


@pytest.mark.parametrize("case_id", [i for i in IDS if CASES[i]["route"] == "watch"])
def test_recorded_watcher_builds_and_passes_the_gate(case_id: str) -> None:
    record = load(case_id)
    answers = [a["content"] for a in record["answers"] if a["stage"] == "codegen"]
    # school_calendar's later answers were retries forced by the pre-T-04 rejection (they fell
    # back to web_diff); its first answer is the model's own choice.
    answer = answers[0] if case_id == "school_calendar" else answers[-1]
    built = build(answer, record["text"])
    endpoints = [e for a in built.adapters for e in a.endpoints]
    gate.check(built.code, [a.name for a in built.adapters], endpoints)
    assert CASES[case_id]["adapter"] in [a.name for a in built.adapters]


def test_school_calendar_declares_the_canonical_ics_path() -> None:
    record = load("school_calendar")
    canonical = "/calendar/ical/de.german%23holiday@group.v.calendar.google.com/public/basic.ics"
    for answer in [a["content"] for a in record["answers"] if a["stage"] == "codegen"]:
        built = build(answer, record["text"])  # every attempt now builds …
        paths = [e.path for a in built.adapters for e in a.endpoints]
        assert paths == [canonical]  # … with the one canonical path
        gate.check(built.code, [a.name for a in built.adapters], [
            e for a in built.adapters for e in a.endpoints
        ])
