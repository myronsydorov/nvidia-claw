from pathlib import Path

import pytest
from fixture_loader import load_json_fixture
from warden.adapters.transit_bvg import declare
from warden.compiler.policy import generate_policy
from watcher_runtime.adapters.transit_bvg import parse

_EXAMPLE_STOP_ID = "900000100003"
_EXAMPLE_WHY = "check departures for the platform near home"
_SNAPSHOT_PATH = Path(__file__).parent.parent.parent.parent / "policies/examples/transit_bvg.yaml"


def test_declare_builds_one_exact_departures_path() -> None:
    adapter = declare(stop_id=_EXAMPLE_STOP_ID, why=_EXAMPLE_WHY)
    assert len(adapter.endpoints) == 1
    endpoint = adapter.endpoints[0]
    assert endpoint.host == "v6.bvg.transport.rest"
    assert endpoint.path == f"/stops/{_EXAMPLE_STOP_ID}/departures"
    assert endpoint.why == _EXAMPLE_WHY
    assert adapter.secrets == []


@pytest.mark.parametrize("stop_id", ["", "abc", "123abc", "900000100003;drop"])
def test_declare_rejects_non_numeric_stop_ids(stop_id: str) -> None:
    with pytest.raises(ValueError, match="numeric"):
        declare(stop_id=stop_id, why=_EXAMPLE_WHY)


def test_parse_summarizes_departures_from_fixture() -> None:
    raw = load_json_fixture("transit_bvg", "departures.json")
    parsed = parse(raw)
    assert parsed == {
        "departures": [
            {
                "line": "U2",
                "direction": "Pankow",
                "when": "2026-09-30T10:15:00+02:00",
                "planned_when": "2026-09-30T10:14:00+02:00",
                "delay_s": 60,
                "platform": "2",
                "cancelled": False,
            },
            {
                "line": "M5",
                "direction": "Hackescher Markt",
                # Cancelled: no realtime `when`, so the planned time; no delay data -> 0.
                "when": "2026-09-30T10:18:00+02:00",
                "planned_when": "2026-09-30T10:18:00+02:00",
                "delay_s": 0,
                "platform": "1",
                "cancelled": True,
            },
        ]
    }


def test_parse_handles_no_departures() -> None:
    assert parse({"departures": []}) == {"departures": []}


def test_policy_snapshot_matches_golden_file() -> None:
    adapter = declare(stop_id=_EXAMPLE_STOP_ID, why=_EXAMPLE_WHY)
    policy_yaml, _ = generate_policy([adapter], sandbox_name="cw-transit-bvg1")
    assert policy_yaml == _SNAPSHOT_PATH.read_text()


def test_policy_snapshot_has_no_wildcards() -> None:
    snapshot = _SNAPSHOT_PATH.read_text()
    assert "*" not in snapshot
    assert "?" not in snapshot
