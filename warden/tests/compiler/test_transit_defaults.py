"""Transit default (2026-10-02): only the direction of travel, only cancellations or delays of
10+ minutes, unless the worry says otherwise.

Last night's S7 watcher would have alerted on any delay over 1 minute, in either direction.
"""

import json

import pytest
from warden.compiler import gate
from warden.compiler.codegen import CodegenError, build
from watcher_runtime.adapters.transit_bvg import disruptions


def dep(direction: str, delay_min: int = 0, cancelled: bool = False, line: str = "S7") -> dict:  # type: ignore[type-arg]
    return {
        "line": line,
        "direction": direction,
        "when": "2026-10-02T09:06:00+02:00",
        "planned_when": "2026-10-02T09:06:00+02:00",
        "delay_s": delay_min * 60,
        "platform": "3",
        "cancelled": cancelled,
    }


TO_POTSDAM = "S Potsdam Hauptbahnhof"
TO_AHRENSFELDE = "S Ahrensfelde"


def test_last_nights_noise_is_silent() -> None:
    board = {
        "departures": [
            dep(TO_POTSDAM, 2),
            dep(TO_POTSDAM, 9),
            dep(TO_AHRENSFELDE, 30),
            dep(TO_AHRENSFELDE, cancelled=True),
            dep(TO_POTSDAM, 15, line="S5"),
        ]
    }
    found = disruptions(board, "S7", toward="Potsdam Hbf")
    assert found == {"matched": 2, "disrupted": []}


def test_a_cancellation_or_ten_minutes_in_my_direction_alerts() -> None:
    board = {"departures": [dep(TO_POTSDAM, 10), dep(TO_POTSDAM, cancelled=True),
                            dep(TO_POTSDAM, 3)]}  # fmt: skip
    found = disruptions(board, "s7", toward="Potsdam Hbf")
    assert found["matched"] == 3
    assert [(d["delay_min"], d["cancelled"]) for d in found["disrupted"]] == [
        (10, False),
        (0, True),
    ]


def test_the_worry_can_ask_for_a_lower_threshold_or_both_directions() -> None:
    board = {"departures": [dep(TO_POTSDAM, 5), dep(TO_AHRENSFELDE, 6)]}
    assert len(disruptions(board, "S7", min_delay_min=5)["disrupted"]) == 2


def test_a_direction_that_matches_nothing_reports_zero_matched() -> None:
    board = {"departures": [dep(TO_POTSDAM, 20)]}
    assert disruptions(board, "S7", toward="Wannsee") == {"matched": 0, "disrupted": []}


WORRY = "What if the S7 from Lichtenberg toward Potsdam Hbf is disrupted around 9:00?"


def answer(judge: str) -> str:
    plan = {"adapters": [{"name": "transit_bvg", "params": {"stop_id": "900160004"}}],
            "interval_s": 300}  # fmt: skip
    code = (
        "from watcher_runtime import harness\n"
        "from watcher_runtime.adapters import transit_bvg\n"
        'data = transit_bvg.fetch("900160004")\n'
        f"{judge}\n"
        'harness.emit("ok", "S7 looks normal.", "BVG")\n'
    )
    return f"```json\n{json.dumps(plan)}\n```\n```python\n{code}```"


WORRY_WITH_ID = WORRY + " (BVG stop 900160004)"


def test_a_transit_watcher_that_judges_by_hand_is_sent_back() -> None:
    by_hand = 'late = [d for d in data["departures"] if d["delay_s"] > 60]'
    with pytest.raises(CodegenError, match="disruptions"):
        build(answer(by_hand), WORRY_WITH_ID)


def test_the_default_call_builds_and_passes_the_gate() -> None:
    built = build(answer('found = transit_bvg.disruptions(data, "S7", toward="Potsdam Hbf")'),
                  WORRY_WITH_ID)  # fmt: skip
    endpoints = [e for a in built.adapters for e in a.endpoints]
    gate.check(built.code, [a.name for a in built.adapters], endpoints)


def test_a_lower_threshold_needs_the_worry_to_name_it() -> None:
    low = 'found = transit_bvg.disruptions(data, "S7", toward="Potsdam Hbf", min_delay_min=1)'
    with pytest.raises(CodegenError, match="min_delay_min=10"):
        build(answer(low), WORRY_WITH_ID)
    five = low.replace("=1)", "=5)")
    build(answer(five), WORRY_WITH_ID + " Tell me if it's more than 5 minutes late.")
