"""Replays real NVIDIA Build answers from `make eval-compiler ARGS=--record` (no network).

Each recorded triage must still parse to the case's labelled route, and each watch
case's last code-generation answer must still build and pass the static gate,
except school_calendar, whose percent-encoded ICS path our Endpoint validator
rejects (see PLAN.md T-09).
"""

import json
from pathlib import Path

import pytest
import yaml
from warden.compiler import gate
from warden.compiler.codegen import CodegenError, build
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
    answer = [a["content"] for a in record["answers"] if a["stage"] == "codegen"][-1]
    if case_id == "school_calendar":
        with pytest.raises(CodegenError, match="params rejected"):
            build(answer, record["text"])
        return
    built = build(answer, record["text"])
    endpoints = [e for a in built.adapters for e in a.endpoints]
    gate.check(built.code, [a.name for a in built.adapters], endpoints)
    assert CASES[case_id]["adapter"] in [a.name for a in built.adapters]
