from pathlib import Path

from fixture_loader import load_text_fixture
from warden.adapters.ics_calendar import declare
from warden.compiler.policy import generate_policy
from watcher_runtime.adapters.ics_calendar import parse

_EXAMPLE_URL = "https://cal.example.com/family/events.ics"
_EXAMPLE_WHY = "check for new calendar events"
_SNAPSHOT_PATH = Path(__file__).parent.parent.parent.parent / "policies/examples/ics_calendar.yaml"


def test_declare_extracts_host_and_path_from_the_worry_url() -> None:
    adapter = declare(url=_EXAMPLE_URL, why=_EXAMPLE_WHY)
    endpoint = adapter.endpoints[0]
    assert endpoint.host == "cal.example.com"
    assert endpoint.path == "/family/events.ics"


def test_parse_extracts_events_and_unfolds_long_lines() -> None:
    raw_ics = load_text_fixture("ics_calendar", "calendar.ics")
    parsed = parse(raw_ics)
    assert parsed == {
        "events": [
            {
                "uid": "event1@example.com",
                "summary": "Dentist appointment",
                "location": "123 Main St",
                "start": "20261005T090000Z",
                "end": "20261005T100000Z",
            },
            {
                "uid": "event2@example.com",
                "summary": (
                    "Visa interview with a long summary line that needs folding "
                    "across multiple physical lines per RFC 5545"
                ),
                "location": None,
                "start": "20261010T140000Z",
                "end": "20261010T150000Z",
            },
        ]
    }


def test_parse_handles_a_calendar_with_no_events() -> None:
    raw_ics = load_text_fixture("ics_calendar", "empty_calendar.ics")
    assert parse(raw_ics) == {"events": []}


def test_policy_snapshot_matches_golden_file() -> None:
    adapter = declare(url=_EXAMPLE_URL, why=_EXAMPLE_WHY)
    policy_yaml, _ = generate_policy([adapter], sandbox_name="cw-ics1")
    assert policy_yaml == _SNAPSHOT_PATH.read_text()


def test_policy_snapshot_has_no_wildcards() -> None:
    snapshot = _SNAPSHOT_PATH.read_text()
    assert "*" not in snapshot
    assert "?" not in snapshot
