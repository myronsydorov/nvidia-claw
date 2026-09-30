from pathlib import Path

import pytest
from fixture_loader import load_json_fixture
from warden.adapters.http_json import declare
from warden.compiler.policy import generate_policy
from watcher_runtime.adapters.http_json import parse

_EXAMPLE_URL = "https://status.example.com/api/slots"
_EXAMPLE_WHY = "check appointment slot availability"
_EXAMPLE_SECRETS = ["EXAMPLE_STATUS_API_TOKEN"]
_SNAPSHOT_PATH = Path(__file__).parent.parent.parent.parent / "policies/examples/http_json.yaml"


def test_declare_extracts_host_and_path_and_carries_named_secrets() -> None:
    adapter = declare(url=_EXAMPLE_URL, why=_EXAMPLE_WHY, secrets=_EXAMPLE_SECRETS)
    assert len(adapter.endpoints) == 1
    endpoint = adapter.endpoints[0]
    assert endpoint.host == "status.example.com"
    assert endpoint.path == "/api/slots"
    assert adapter.secrets == _EXAMPLE_SECRETS


def test_declare_defaults_to_no_secrets() -> None:
    adapter = declare(url=_EXAMPLE_URL, why=_EXAMPLE_WHY)
    assert adapter.secrets == []


def test_declare_rejects_non_https_urls() -> None:
    with pytest.raises(ValueError, match="https"):
        declare(url="http://status.example.com/api/slots", why=_EXAMPLE_WHY)


def test_parse_passes_through_a_dict_response_unchanged() -> None:
    raw = load_json_fixture("http_json", "status_response.json")
    assert parse(raw) == raw


def test_parse_wraps_a_bare_list_response_under_data() -> None:
    raw = load_json_fixture("http_json", "bare_list_response.json")
    assert parse(raw) == {"data": raw}


def test_policy_snapshot_matches_golden_file() -> None:
    adapter = declare(url=_EXAMPLE_URL, why=_EXAMPLE_WHY, secrets=_EXAMPLE_SECRETS)
    policy_yaml, _ = generate_policy([adapter], sandbox_name="cw-http-json1")
    assert policy_yaml == _SNAPSHOT_PATH.read_text()


def test_policy_snapshot_has_no_wildcards() -> None:
    snapshot = _SNAPSHOT_PATH.read_text()
    assert "*" not in snapshot
    assert "?" not in snapshot
