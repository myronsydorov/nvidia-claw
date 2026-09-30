from pathlib import Path

from fixture_loader import load_json_fixture
from warden.adapters.parcel_dhl import ADAPTER
from warden.compiler.policy import generate_policy
from watcher_runtime.adapters.parcel_dhl import parse

_SNAPSHOT_PATH = Path(__file__).parent.parent.parent.parent / "policies/examples/parcel_dhl.yaml"


def test_adapter_matches_the_contracts_example_exactly() -> None:
    assert ADAPTER.name == "parcel_dhl"
    assert ADAPTER.secrets == ["DHL_API_KEY"]
    assert len(ADAPTER.endpoints) == 1
    endpoint = ADAPTER.endpoints[0]
    assert endpoint.host == "api-eu.dhl.com"
    assert endpoint.port == 443
    assert endpoint.method == "GET"
    assert endpoint.path == "/track/shipments"
    assert endpoint.why == "check parcel status"


def test_parse_in_transit_fixture() -> None:
    raw = load_json_fixture("parcel_dhl", "in_transit.json")
    assert parse(raw) == {
        "found": True,
        "id": "00340434161094123456",
        "status_code": "transit",
        "status": "Transit",
        "description": "The shipment has departed from a DHL facility",
        "estimated_delivery": "2026-10-01T18:00:00+02:00",
        "delivered": False,
    }


def test_parse_delivered_fixture() -> None:
    raw = load_json_fixture("parcel_dhl", "delivered.json")
    parsed = parse(raw)
    assert parsed["delivered"] is True
    assert parsed["status_code"] == "delivered"


def test_parse_not_found_fixture() -> None:
    raw = load_json_fixture("parcel_dhl", "not_found.json")
    assert parse(raw) == {"found": False}


def test_policy_snapshot_matches_golden_file() -> None:
    policy_yaml, _ = generate_policy([ADAPTER], sandbox_name="cw-parcel-dhl1")
    assert policy_yaml == _SNAPSHOT_PATH.read_text()


def test_policy_snapshot_has_no_wildcards() -> None:
    snapshot = _SNAPSHOT_PATH.read_text()
    assert "*" not in snapshot
    assert "?" not in snapshot
