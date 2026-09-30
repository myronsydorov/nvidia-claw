from pathlib import Path

import pytest
from fixture_loader import load_text_fixture
from warden.adapters.web_diff import declare
from warden.compiler.policy import generate_policy
from watcher_runtime.adapters.web_diff import parse

_EXAMPLE_URL = "https://visa.example.com/appointments"
_EXAMPLE_WHY = "check for a new visa appointment slot"
_SNAPSHOT_PATH = Path(__file__).parent.parent.parent.parent / "policies/examples/web_diff.yaml"


def test_declare_extracts_host_and_path_from_the_worry_url() -> None:
    adapter = declare(url=_EXAMPLE_URL, why=_EXAMPLE_WHY)
    assert len(adapter.endpoints) == 1
    endpoint = adapter.endpoints[0]
    assert endpoint.host == "visa.example.com"
    assert endpoint.path == "/appointments"
    assert endpoint.why == _EXAMPLE_WHY
    assert adapter.secrets == []


def test_declare_rejects_non_https_urls() -> None:
    with pytest.raises(ValueError, match="https"):
        declare(url="http://visa.example.com/appointments", why=_EXAMPLE_WHY)


def test_declare_rejects_bare_ip_literals() -> None:
    with pytest.raises(ValueError, match="IP literal"):
        declare(url="https://169.254.169.254/appointments", why=_EXAMPLE_WHY)


def test_parse_with_no_baseline_reports_no_baseline() -> None:
    current = load_text_fixture("web_diff", "page_v1.html")
    parsed = parse(None, current)
    assert parsed["status"] == "no_baseline"
    assert "No appointments" in parsed["excerpt"]


def test_parse_unchanged_content_is_unchanged_despite_reformatting() -> None:
    previous = load_text_fixture("web_diff", "page_v1.html")
    current = load_text_fixture("web_diff", "page_v1_reformatted.html")
    parsed = parse(previous, current)
    assert parsed["status"] == "unchanged"


def test_parse_changed_content_is_changed() -> None:
    previous = load_text_fixture("web_diff", "page_v1.html")
    current = load_text_fixture("web_diff", "page_v2.html")
    parsed = parse(previous, current)
    assert parsed["status"] == "changed"
    assert "3 appointments" in parsed["excerpt"]


def test_policy_snapshot_matches_golden_file() -> None:
    adapter = declare(url=_EXAMPLE_URL, why=_EXAMPLE_WHY)
    policy_yaml, _ = generate_policy([adapter], sandbox_name="cw-web-diff1")
    assert policy_yaml == _SNAPSHOT_PATH.read_text()


def test_policy_snapshot_has_no_wildcards() -> None:
    snapshot = _SNAPSHOT_PATH.read_text()
    assert "*" not in snapshot
    assert "?" not in snapshot
