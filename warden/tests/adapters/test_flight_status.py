from pathlib import Path

from fixture_loader import load_json_fixture
from warden.adapters.flight_status import ADAPTER
from warden.compiler.policy import generate_policy
from watcher_runtime.adapters.flight_status import parse

_SNAPSHOT_PATH = Path(__file__).parent.parent.parent.parent / "policies/examples/flight_status.yaml"


def test_adapter_declares_one_endpoint_with_no_secrets() -> None:
    assert ADAPTER.secrets == []
    endpoint = ADAPTER.endpoints[0]
    assert endpoint.host == "opensky-network.org"
    assert endpoint.path == "/api/states/all"


def test_parse_in_flight_fixture() -> None:
    raw = load_json_fixture("flight_status", "in_flight.json")
    assert parse(raw) == {
        "found": True,
        "icao24": "3c6444",
        "callsign": "DLH9LF",
        "origin_country": "Germany",
        "longitude": 8.5432,
        "latitude": 50.0379,
        "baro_altitude_m": 10972.8,
        "on_ground": False,
        "velocity_ms": 245.6,
    }


def test_parse_not_found_fixture() -> None:
    raw = load_json_fixture("flight_status", "not_found.json")
    assert parse(raw) == {"found": False}


def test_policy_snapshot_matches_golden_file() -> None:
    policy_yaml, _ = generate_policy([ADAPTER], sandbox_name="cw-flight1")
    assert policy_yaml == _SNAPSHOT_PATH.read_text()


def test_policy_snapshot_has_no_wildcards() -> None:
    snapshot = _SNAPSHOT_PATH.read_text()
    assert "*" not in snapshot
    assert "?" not in snapshot
