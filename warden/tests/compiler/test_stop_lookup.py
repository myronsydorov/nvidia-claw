"""S7 incident (2026-10-02): stop ids come from a real lookup, never the model's memory.

The model wrote `/stops/8011120/departures`; BVG answers that id with NOT_FOUND, so every
dry run failed and the worry was parked. Fixture: BVG `/locations?query=Lichtenberg`
(recorded 2026-10-02, trimmed to the fields the lookup reads).
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import pytest
from warden.adapters import bvg_lookup
from warden.compiler import codegen, gate

FIXTURE = Path(__file__).parent.parent / "fixtures" / "bvg_lookup" / "locations_lichtenberg.json"
S7_WORRY = (
    "What if the S-Bahn S7 is disrupted today, Friday 2 October, around 9:00 when I need to "
    "go from Lichtenberg to Potsdam Hbf for work?"
)


@pytest.fixture
def bvg(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, str]]:
    calls: list[dict[str, str]] = []

    async def fake(path: str, params: dict[str, str]) -> Any:
        calls.append({"path": path, **params})
        return json.loads(FIXTURE.read_text())

    monkeypatch.setattr(bvg_lookup, "fetch", fake)
    return calls


def answer(params: dict[str, str], stop_literal: str) -> str:
    plan = json.dumps({"adapters": [{"name": "transit_bvg", "params": params}],
                       "interval_s": 300})  # fmt: skip
    code = (
        "from watcher_runtime import harness\n"
        "from watcher_runtime.adapters import transit_bvg\n"
        f'STOP_ID = "{stop_literal}"\n'
        'data = transit_bvg.fetch(STOP_ID, when="2026-10-02T06:30:00+00:00", duration_min=60)\n'
        'harness.emit("ok", "S7 looks normal.", "BVG")\n'
    )
    return f"```json\n{plan}\n```\n```python\n{code}```"


def test_lookup_finds_s_u_lichtenberg_for_s7(bvg: list[dict[str, str]]) -> None:
    stop = asyncio.run(bvg_lookup.find_stop("Lichtenberg", "S7"))
    assert stop is not None
    assert (stop.id, stop.name) == ("900160004", "S+U Lichtenberg Bhf (Berlin)")
    assert "S7" in stop.lines
    assert bvg[0]["path"] == "/locations" and bvg[0]["query"] == "Lichtenberg"


def test_lookup_skips_stops_without_the_line(bvg: list[dict[str, str]]) -> None:
    assert asyncio.run(bvg_lookup.find_stop("Lichtenberg", "S1")) is None


def test_the_invented_stop_id_from_the_incident_is_refused() -> None:
    # The model's 8011120 isn't in the worry text: ask the person, never trust memory.
    with pytest.raises(codegen.MissingInput):
        codegen.build(answer({"stop_id": "8011120"}, "8011120"), S7_WORRY)


def test_a_stop_id_the_person_wrote_is_still_accepted() -> None:
    text = "Is the S1 from Alexanderplatz (BVG stop 900100003) going to be cancelled?"
    built = codegen.build(answer({"stop_id": "900100003"}, "900100003"), text)
    assert built.adapters[0].endpoints[0].path == "/stops/900100003/departures"


def test_a_named_stop_is_pinned_from_the_lookup(bvg: list[dict[str, str]]) -> None:
    content = answer({"stop": "Lichtenberg", "line": "S7"}, codegen.STOP_PLACEHOLDER)
    queries = codegen.stop_queries(content)
    assert queries == [("Lichtenberg", "S7")]
    found = asyncio.run(bvg_lookup.find_stop(*queries[0]))
    assert found is not None
    built = codegen.build(content, S7_WORRY, {queries[0]: found.id})
    # Pinned in the declared path (so the policy and the card) and in run.py.
    assert built.adapters[0].endpoints[0].path == "/stops/900160004/departures"
    assert 'STOP_ID = "900160004"' in built.code
    assert codegen.STOP_PLACEHOLDER not in built.code
    endpoints = [e for a in built.adapters for e in a.endpoints]
    gate.check(built.code, [a.name for a in built.adapters], endpoints)


def test_a_stop_the_lookup_could_not_find_asks_the_person() -> None:
    content = answer({"stop": "Lichtenberg", "line": "S7"}, codegen.STOP_PLACEHOLDER)
    with pytest.raises(codegen.MissingInput) as info:
        codegen.build(content, S7_WORRY, {})
    assert "couldn't find that stop" in info.value.reason


def test_a_stop_name_not_in_the_worry_is_refused() -> None:
    content = answer({"stop": "Ostkreuz", "line": "S7"}, codegen.STOP_PLACEHOLDER)
    with pytest.raises(codegen.MissingInput):
        codegen.build(content, S7_WORRY, {("Ostkreuz", "S7"): "900120003"})


def test_the_placeholder_is_required() -> None:
    content = answer({"stop": "Lichtenberg", "line": "S7"}, "900160004")
    with pytest.raises(codegen.CodegenError, match="BVG_STOP_ID"):
        codegen.build(content, S7_WORRY, {("Lichtenberg", "S7"): "900160004"})
