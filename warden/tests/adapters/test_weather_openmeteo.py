from pathlib import Path

from fixture_loader import load_json_fixture
from warden.adapters.weather_openmeteo import ADAPTER
from warden.compiler.policy import generate_policy
from watcher_runtime.adapters.weather_openmeteo import parse

_SNAPSHOT_PATH = (
    Path(__file__).parent.parent.parent.parent / "policies/examples/weather_openmeteo.yaml"
)


def test_adapter_declares_one_endpoint_with_no_secrets() -> None:
    assert ADAPTER.secrets == []
    assert len(ADAPTER.endpoints) == 1
    endpoint = ADAPTER.endpoints[0]
    assert endpoint.host == "api.open-meteo.com"
    assert endpoint.path == "/v1/forecast"


def test_parse_forecast_fixture() -> None:
    raw = load_json_fixture("weather_openmeteo", "forecast.json")
    assert parse(raw) == {
        "current": {
            "time": "2026-09-30T10:00",
            "temperature_c": 14.2,
            "precipitation_mm": 0.0,
            "weather_code": 3,
        },
        "daily": [
            {
                "date": "2026-09-30",
                "temperature_max_c": 16.1,
                "temperature_min_c": 9.3,
                "precipitation_mm": 0.0,
                "weather_code": 3,
            },
            {
                "date": "2026-10-01",
                "temperature_max_c": 15.0,
                "temperature_min_c": 8.1,
                "precipitation_mm": 2.4,
                "weather_code": 61,
            },
        ],
    }


def test_policy_snapshot_matches_golden_file() -> None:
    policy_yaml, _ = generate_policy([ADAPTER], sandbox_name="cw-weather-om1")
    assert policy_yaml == _SNAPSHOT_PATH.read_text()


def test_policy_snapshot_has_no_wildcards() -> None:
    snapshot = _SNAPSHOT_PATH.read_text()
    assert "*" not in snapshot
    assert "?" not in snapshot
