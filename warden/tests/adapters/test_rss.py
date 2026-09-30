from pathlib import Path

from fixture_loader import load_text_fixture
from warden.adapters.rss import declare
from warden.compiler.policy import generate_policy
from watcher_runtime.adapters.rss import parse

_EXAMPLE_URL = "https://council.example.gov/notices/feed.xml"
_EXAMPLE_WHY = "check for new council notices"
_SNAPSHOT_PATH = Path(__file__).parent.parent.parent.parent / "policies/examples/rss.yaml"


def test_declare_extracts_host_and_path_from_the_worry_url() -> None:
    adapter = declare(url=_EXAMPLE_URL, why=_EXAMPLE_WHY)
    endpoint = adapter.endpoints[0]
    assert endpoint.host == "council.example.gov"
    assert endpoint.path == "/notices/feed.xml"


def test_parse_extracts_items_from_fixture() -> None:
    raw_xml = load_text_fixture("rss", "feed.xml")
    parsed = parse(raw_xml)
    assert parsed == {
        "items": [
            {
                "title": "Street closure: Main St, Oct 3-5",
                "link": "https://council.example.gov/notices/street-closure-main-st",
                "published": "Tue, 29 Sep 2026 09:00:00 GMT",
                "guid": "https://council.example.gov/notices/street-closure-main-st",
            },
            {
                "title": "Public hearing: zoning change rescheduled",
                "link": "https://council.example.gov/notices/zoning-hearing-reschedule",
                "published": "Mon, 28 Sep 2026 15:30:00 GMT",
                "guid": "https://council.example.gov/notices/zoning-hearing-reschedule",
            },
        ]
    }


def test_parse_handles_a_feed_with_no_items() -> None:
    raw_xml = load_text_fixture("rss", "empty_feed.xml")
    assert parse(raw_xml) == {"items": []}


def test_policy_snapshot_matches_golden_file() -> None:
    adapter = declare(url=_EXAMPLE_URL, why=_EXAMPLE_WHY)
    policy_yaml, _ = generate_policy([adapter], sandbox_name="cw-rss1")
    assert policy_yaml == _SNAPSHOT_PATH.read_text()


def test_policy_snapshot_has_no_wildcards() -> None:
    snapshot = _SNAPSHOT_PATH.read_text()
    assert "*" not in snapshot
    assert "?" not in snapshot
