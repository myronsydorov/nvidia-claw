"""Integration: a watcher using several adapters gets exactly their union,
deduped, with no cross-contamination — the scenario policies/examples/
multi_adapter.yaml documents.
"""

from pathlib import Path

from warden.adapters.parcel_dhl import ADAPTER as DHL
from warden.adapters.transit_bvg import declare as declare_bvg
from warden.adapters.weather_openmeteo import ADAPTER as WEATHER
from warden.compiler.policy import generate_policy

_SNAPSHOT_PATH = Path(__file__).parent.parent.parent.parent / "policies/examples/multi_adapter.yaml"
_STOP_ID = "900000100003"
_STOP_WHY = "check departures for the platform near home"


def test_three_adapters_produce_exactly_three_egress_rules() -> None:
    bvg = declare_bvg(stop_id=_STOP_ID, why=_STOP_WHY)
    policy_yaml, summary = generate_policy([DHL, WEATHER, bvg], sandbox_name="cw-multi1")

    assert len(summary) == 3
    hosts = {line.host for line in summary}
    assert hosts == {"api-eu.dhl.com", "api.open-meteo.com", "v6.bvg.transport.rest"}

    # a two-adapter watcher must not see the third adapter's host at all
    two_adapter_yaml, _ = generate_policy([DHL, WEATHER], sandbox_name="cw-multi2")
    assert "v6.bvg.transport.rest" not in two_adapter_yaml
    assert policy_yaml != two_adapter_yaml


def test_policy_snapshot_matches_golden_file() -> None:
    bvg = declare_bvg(stop_id=_STOP_ID, why=_STOP_WHY)
    policy_yaml, _ = generate_policy([DHL, WEATHER, bvg], sandbox_name="cw-multi1")
    assert policy_yaml == _SNAPSHOT_PATH.read_text()


def test_policy_snapshot_has_no_wildcards() -> None:
    snapshot = _SNAPSHOT_PATH.read_text()
    assert "*" not in snapshot
    assert "?" not in snapshot
