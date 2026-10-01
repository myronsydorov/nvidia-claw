"""Local inputs for the "normal day" signal. Nothing here touches the network.

- Computer activity: the OS idle time (macOS `ioreg` HIDIdleTime, Linux/X11 `xprintidle`).
  `CUSTODY_ACTIVITY=off` disables it, e.g. on a headless host or in tests.
- Calendar busy/free: a **local** .ics file (`CUSTODY_CALENDAR_ICS`), e.g. an exported or
  OS-synced calendar. Honest limits: no RRULE expansion; TZID times are read as the host's
  local time; all-day events, TRANSP:TRANSPARENT and STATUS:CANCELLED never count as busy.
"""

import logging
import os
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol

log = logging.getLogger(__name__)

MAX_ICS_BYTES = 2 * 1024 * 1024


class ActivityProbe(Protocol):
    def idle_seconds(self) -> float | None: ...


class NoProbe:
    def idle_seconds(self) -> float | None:
        return None


class MacIdleProbe:
    _pattern = re.compile(r'"HIDIdleTime"\s*=\s*(\d+)')

    def idle_seconds(self) -> float | None:
        out = _run(["/usr/sbin/ioreg", "-c", "IOHIDSystem", "-d", "4"])
        match = self._pattern.search(out or "")
        return int(match.group(1)) / 1e9 if match else None


class XprintidleProbe:
    def __init__(self, path: str) -> None:
        self._path = path

    def idle_seconds(self) -> float | None:
        out = (_run([self._path]) or "").strip()
        return int(out) / 1000 if out.isdigit() else None


def _run(argv: list[str]) -> str | None:
    try:
        result = subprocess.run(argv, capture_output=True, text=True, timeout=5, check=False)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return result.stdout if result.returncode == 0 else None


def probe_from_env() -> ActivityProbe:
    if os.environ.get("CUSTODY_ACTIVITY", "auto") == "off":
        return NoProbe()
    if sys.platform == "darwin" and Path("/usr/sbin/ioreg").exists():
        return MacIdleProbe()
    if (path := shutil.which("xprintidle")) is not None:
        return XprintidleProbe(path)
    log.info("no activity probe on this host; the signal will rely on check-ins")
    return NoProbe()


# --- calendar -----------------------------------------------------------------------------


def _unfold(raw: str) -> list[str]:
    lines: list[str] = []
    for line in raw.replace("\r\n", "\n").split("\n"):
        if line.startswith((" ", "\t")) and lines:
            lines[-1] += line[1:]
        else:
            lines.append(line.rstrip())
    return lines


def _parse_time(params: str, value: str) -> datetime | None:
    if "VALUE=DATE" in params.upper() and "DATE-TIME" not in params.upper():
        return None  # all-day
    try:
        if value.endswith("Z"):
            return datetime.strptime(value, "%Y%m%dT%H%M%SZ").replace(tzinfo=UTC)
        # floating or TZID: read as the host's local time (honest limit, see module doc)
        return datetime.strptime(value, "%Y%m%dT%H%M%S").astimezone()
    except ValueError:
        return None


def busy_at(raw_ics: str, now: datetime) -> bool:
    event: dict[str, tuple[str, str]] | None = None
    for line in _unfold(raw_ics):
        if line == "BEGIN:VEVENT":
            event = {}
        elif line == "END:VEVENT" and event is not None:
            if _is_busy(event, now):
                return True
            event = None
        elif event is not None and ":" in line:
            head, value = line.split(":", 1)
            name, _, params = head.partition(";")
            event[name.upper()] = (params, value.strip())
    return False


def _is_busy(event: dict[str, tuple[str, str]], now: datetime) -> bool:
    if event.get("TRANSP", ("", ""))[1].upper() == "TRANSPARENT":
        return False
    if event.get("STATUS", ("", ""))[1].upper() == "CANCELLED":
        return False
    if "DTSTART" not in event or "DTEND" not in event:
        return False
    start = _parse_time(*event["DTSTART"])
    end = _parse_time(*event["DTEND"])
    return start is not None and end is not None and start <= now < end


def calendar_busy_now(now: datetime) -> bool:
    path = os.environ.get("CUSTODY_CALENDAR_ICS")
    if not path:
        return False
    try:
        file = Path(path)
        if file.stat().st_size > MAX_ICS_BYTES:
            log.warning("calendar file too large; ignoring it")
            return False
        return busy_at(file.read_text(encoding="utf-8", errors="replace"), now)
    except OSError:
        log.warning("calendar file unreadable; ignoring it")
        return False
