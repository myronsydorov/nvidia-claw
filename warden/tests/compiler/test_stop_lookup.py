"""S7 incident (2026-10-02): stop ids come from a real lookup, never the model's memory.

The model wrote `/stops/8011120/departures`; BVG answers that id with NOT_FOUND, so every
dry run failed and the worry was parked. Fixture: BVG `/locations?query=Lichtenberg`
(recorded 2026-10-02, trimmed to the fields the lookup reads).
"""

import asyncio
import json
from pathlib import Path
from typing import Any

import httpx2 as httpx
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
        'found = transit_bvg.disruptions(data, "S7", toward="Potsdam Hbf")\n'
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
    queries = codegen.stop_queries(content, S7_WORRY)
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


def test_only_stop_names_from_the_worry_are_looked_up() -> None:
    # Security review: the model can't make the Warden send arbitrary text to BVG.
    invented = answer({"stop": "Ostkreuz", "line": "S7"}, codegen.STOP_PLACEHOLDER)
    assert codegen.stop_queries(invented, S7_WORRY) == []
    long = answer({"stop": S7_WORRY, "line": "S7"}, codegen.STOP_PLACEHOLDER)
    assert codegen.stop_queries(long, S7_WORRY) == []  # the whole worry: over the length cap


# Stop-lookup incident (2026-10-02, 08:17 Berlin): BVG answered 503 three hand-overs in a row.


def _status_error(code: int) -> httpx.HTTPStatusError:
    request = httpx.Request("GET", "https://v6.bvg.transport.rest/locations")
    response = httpx.Response(code, request=request)
    return httpx.HTTPStatusError("x", request=request, response=response)


@pytest.fixture
def no_sleep(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    slept: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        slept.append(seconds)

    monkeypatch.setattr(bvg_lookup, "sleep", fake_sleep)
    return slept


def _flaky(monkeypatch: pytest.MonkeyPatch, failures: list[Exception]) -> list[str]:
    calls: list[str] = []

    async def fake(path: str, params: dict[str, str]) -> Any:
        calls.append(path)
        if failures:
            raise failures.pop(0)
        return json.loads(FIXTURE.read_text())

    monkeypatch.setattr(bvg_lookup, "fetch", fake)
    return calls


def test_a_503_then_a_timeout_is_retried_with_backoff(
    monkeypatch: pytest.MonkeyPatch, no_sleep: list[float]
) -> None:
    calls = _flaky(monkeypatch, [_status_error(503), httpx.ReadTimeout("slow")])
    stop = asyncio.run(bvg_lookup.find_stop("Lichtenberg", "S7"))
    assert stop is not None and stop.id == "900160004"
    assert len(calls) == 3
    assert no_sleep == [1.0, 3.0]


def test_three_503s_give_up_with_the_status_in_the_reason(
    monkeypatch: pytest.MonkeyPatch, no_sleep: list[float]
) -> None:
    calls = _flaky(monkeypatch, [_status_error(503)] * 3)
    with pytest.raises(bvg_lookup.StopLookupError, match="HTTP 503"):
        asyncio.run(bvg_lookup.find_stop("Lichtenberg", "S7"))
    assert len(calls) == 3  # one try + two retries, no more


def test_a_404_is_not_retried(monkeypatch: pytest.MonkeyPatch, no_sleep: list[float]) -> None:
    calls = _flaky(monkeypatch, [_status_error(404)])
    with pytest.raises(bvg_lookup.StopLookupError):
        asyncio.run(bvg_lookup.find_stop("Lichtenberg", "S7"))
    assert len(calls) == 1 and no_sleep == []


def test_a_resolved_stop_never_needs_the_network_again(
    monkeypatch: pytest.MonkeyPatch, no_sleep: list[float]
) -> None:
    calls = _flaky(monkeypatch, [])
    first = asyncio.run(bvg_lookup.find_stop("Lichtenberg", "S7"))
    assert first is not None and len(calls) == 1
    # BVG goes down; the same stop (any spacing or case) still resolves, from disk.
    _flaky(monkeypatch, [_status_error(503)] * 9)
    again = asyncio.run(bvg_lookup.find_stop("  lichtenberg ", "s7"))
    assert again == first
    cached = json.loads(bvg_lookup.cache_path().read_text())
    assert cached == {
        "lichtenberg|S7": {"id": "900160004", "lines": list(first.lines),
                           "name": "S+U Lichtenberg Bhf (Berlin)"},
    }  # fmt: skip


def test_not_found_is_not_cached(bvg: list[dict[str, str]]) -> None:
    assert asyncio.run(bvg_lookup.find_stop("Lichtenberg", "S1")) is None
    assert asyncio.run(bvg_lookup.find_stop("Lichtenberg", "S1")) is None
    assert len(bvg) == 2


def test_a_corrupt_cache_is_ignored(bvg: list[dict[str, str]]) -> None:
    bvg_lookup.cache_path().write_text('{"lichtenberg|S7": {"id": "x; rm -rf /"}}')
    stop = asyncio.run(bvg_lookup.find_stop("Lichtenberg", "S7"))
    assert stop is not None and stop.id == "900160004"
    assert len(bvg) == 1


def test_a_cached_stop_also_answers_a_query_without_a_line(
    monkeypatch: pytest.MonkeyPatch, no_sleep: list[float]
) -> None:
    _flaky(monkeypatch, [])
    first = asyncio.run(bvg_lookup.find_stop("Lichtenberg", "S7"))
    calls = _flaky(monkeypatch, [_status_error(503)] * 9)
    assert asyncio.run(bvg_lookup.find_stop("Lichtenberg")) == first
    assert calls == []
    with pytest.raises(bvg_lookup.StopLookupError):  # a different line is a different question
        asyncio.run(bvg_lookup.find_stop("Lichtenberg", "U5"))
