from datetime import UTC, datetime, timedelta

import pytest
from warden.reassurance.signal import ActivitySample, SignalInputs, compute, usual_active_hours
from warden.reassurance.sources import busy_at

NOW = datetime(2026, 10, 1, 14, 0, tzinfo=UTC)  # a Thursday, 14:00 UTC


def history(days: int = 7, hours: range = range(8, 22)) -> list[ActivitySample]:
    """Active during `hours` (UTC) on each of the last `days` days, idle samples otherwise."""
    samples = []
    for d in range(1, days + 1):
        day = (NOW - timedelta(days=d)).replace(minute=0)
        for h in range(24):
            samples.append(ActivitySample(ts=day.replace(hour=h), active=h in hours))
    return samples


def result(inputs: SignalInputs, now: datetime = NOW) -> tuple[str, str]:
    answer = compute(now, inputs)
    assert answer.ts == now
    return answer.level, answer.reason


def test_help_wins_over_everything() -> None:
    inputs = SignalInputs(
        help_requested=True, last_check_in=NOW, busy_now=True, samples=history(), idle_s=0
    )
    assert result(inputs) == ("help", "asked_for_help")


def test_a_fresh_check_in_is_normal_even_without_history() -> None:
    assert result(SignalInputs(last_check_in=NOW - timedelta(hours=2))) == (
        "normal",
        "active_as_usual",
    )


def test_an_old_check_in_does_not_count() -> None:
    assert result(SignalInputs(last_check_in=NOW - timedelta(hours=4))) == (
        "unknown",
        "not_enough_data",
    )


def test_busy_calendar_is_do_not_disturb() -> None:
    assert result(SignalInputs(busy_now=True)) == ("normal", "do_not_disturb")


def test_too_little_history_is_honestly_unknown() -> None:
    assert result(SignalInputs(samples=history(days=2), idle_s=0)) == ("unknown", "not_enough_data")


def test_recent_activity_is_normal() -> None:
    assert result(SignalInputs(samples=history(), idle_s=600)) == ("normal", "active_as_usual")


def test_long_quiet_in_a_usually_active_hour_is_unusual() -> None:
    assert result(SignalInputs(samples=history(), idle_s=3 * 3600)) == (
        "unusual",
        "quieter_than_usual",
    )


def test_short_quiet_in_an_active_hour_is_still_normal() -> None:
    assert result(SignalInputs(samples=history(), idle_s=3600)) == ("normal", "active_as_usual")


def test_quiet_at_night_is_normal() -> None:
    night = NOW.replace(hour=3)
    assert result(SignalInputs(samples=history(), idle_s=5 * 3600), night) == (
        "normal",
        "active_as_usual",
    )


def test_without_a_probe_the_last_active_sample_is_used() -> None:
    samples = history() + [ActivitySample(ts=NOW - timedelta(minutes=10), active=True)]
    assert result(SignalInputs(samples=samples)) == ("normal", "active_as_usual")
    assert result(SignalInputs(samples=history())) == ("unusual", "quieter_than_usual")


def test_learned_hours_need_half_the_days() -> None:
    samples = history(days=6, hours=range(9, 18))
    # 20:00 only on 2 of 6 days: not "usual".
    for d in (1, 2):
        samples.append(ActivitySample(ts=(NOW - timedelta(days=d)).replace(hour=20), active=True))
    usual, days = usual_active_hours(NOW, samples)
    assert days == 6
    assert usual == set(range(9, 18))


def test_history_older_than_two_weeks_is_ignored() -> None:
    old = [ActivitySample(ts=NOW - timedelta(days=20 + d), active=True) for d in range(5)]
    assert usual_active_hours(NOW, old) == (set(), 0)


ICS = """BEGIN:VCALENDAR
BEGIN:VEVENT
SUMMARY:Dentist
DTSTART:20261001T133000Z
DTEND:20261001T143000Z
END:VEVENT
BEGIN:VEVENT
SUMMARY:Focus (free)
TRANSP:TRANSPARENT
DTSTART:20261001T150000Z
DTEND:20261001T160000Z
END:VEVENT
BEGIN:VEVENT
SUMMARY:Cancelled
STATUS:CANCELLED
DTSTART:20261001T170000Z
DTEND:20261001T180000Z
END:VEVENT
BEGIN:VEVENT
SUMMARY:Holiday
DTSTART;VALUE=DATE:20261001
DTEND;VALUE=DATE:20261002
END:VEVENT
END:VCALENDAR
"""


@pytest.mark.parametrize(
    ("hour", "minute", "busy"),
    [(14, 0, True), (13, 29, False), (14, 30, False), (15, 30, False), (17, 30, False)],
)
def test_calendar_busy_free(hour: int, minute: int, busy: bool) -> None:
    assert busy_at(ICS, NOW.replace(hour=hour, minute=minute)) is busy


def test_calendar_garbage_is_free() -> None:
    assert (
        busy_at("BEGIN:VEVENT\nDTSTART:nonsense\nDTEND:20261001T150000Z\nEND:VEVENT", NOW) is False
    )
