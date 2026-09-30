import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from watcher_runtime import harness


def test_emit_prints_exactly_one_watch_result(capsys: pytest.CaptureFixture[str]) -> None:
    harness.emit("ok", "  In transit,\n Leipzig hub  ", "DHL", {"status": "transit"}, 1800)
    out = capsys.readouterr().out
    assert out.count("\n") == 1
    result = json.loads(out)
    assert result["status"] == "ok"
    assert result["summary"] == "In transit, Leipzig hub"
    assert result["evidence"]["source"] == "DHL"
    assert result["evidence"]["data"] == {"status": "transit"}
    assert result["fear_came_true"] is None
    assert result["next_check_s"] == 1800
    datetime.fromisoformat(result["evidence"]["checked_at"])


def test_emit_caps_summary_and_rejects_unknown_status(capsys: pytest.CaptureFixture[str]) -> None:
    harness.emit("act_now", "x" * 500, "s")
    assert len(json.loads(capsys.readouterr().out)["summary"]) == 140
    with pytest.raises(ValueError):
        harness.emit("panic", "no", "s")  # type: ignore[arg-type]


def test_fail_emits_error(capsys: pytest.CaptureFixture[str]) -> None:
    harness.fail("The page could not be read.")
    assert json.loads(capsys.readouterr().out)["status"] == "error"


def test_harness_offers_no_way_to_read_a_secret() -> None:
    assert not hasattr(harness, "secret")
    assert "secret" not in harness.__all__


def test_parse_time_and_hours_until() -> None:
    assert harness.parse_time("2026-10-02T16:00:00Z") == datetime(2026, 10, 2, 16, tzinfo=UTC)
    assert harness.parse_time("2026-10-02") == datetime(2026, 10, 2, tzinfo=UTC)
    soon = (datetime.now(UTC) + timedelta(hours=5)).isoformat()
    assert 4.9 < harness.hours_until(soon) < 5.1


def test_state_round_trip(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(harness, "_STATE_PATH", str(tmp_path / "state.json"))
    assert harness.load_state() == {}
    harness.save_state({"hash": "abc"})
    assert harness.load_state() == {"hash": "abc"}
