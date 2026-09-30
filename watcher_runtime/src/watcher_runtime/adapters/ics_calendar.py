"""Runtime helper for the ics_calendar adapter — only calls the declared endpoint.

`fetch` GETs the one calendar URL the adapter was declared with. `parse` is pure
and fixture-tested; `fetch` is not.

Honest limits: handles basic VEVENT fields only (UID, SUMMARY, LOCATION, DTSTART,
DTEND) after RFC 5545 line-unfolding; no recurrence-rule (RRULE) expansion, no
timezone (VTIMEZONE) resolution beyond passing the raw DTSTART/DTEND value
through as-is.
"""

from typing import Any

import httpx2 as httpx


def fetch(url: str) -> dict[str, Any]:
    with httpx.Client(timeout=10) as client:
        response = client.get(url)
        response.raise_for_status()
        result: dict[str, Any] = parse(response.text)
        return result


def parse(raw_ics: str) -> dict[str, Any]:
    lines = _unfold_lines(raw_ics)
    events: list[dict[str, Any]] = []
    current: dict[str, str] | None = None
    for line in lines:
        if line == "BEGIN:VEVENT":
            current = {}
            continue
        if line == "END:VEVENT":
            if current is not None:
                events.append(
                    {
                        "uid": current.get("UID"),
                        "summary": current.get("SUMMARY"),
                        "location": current.get("LOCATION"),
                        "start": current.get("DTSTART"),
                        "end": current.get("DTEND"),
                    }
                )
            current = None
            continue
        if current is None or ":" not in line:
            continue
        raw_key, value = line.split(":", 1)
        key = raw_key.split(";", 1)[0]
        current[key] = value
    return {"events": events}


def _unfold_lines(raw_ics: str) -> list[str]:
    """RFC 5545 line unfolding: a line starting with a space/tab continues the
    previous line (the leading whitespace is not part of the content)."""
    unfolded: list[str] = []
    for raw_line in raw_ics.replace("\r\n", "\n").split("\n"):
        if raw_line.startswith((" ", "\t")) and unfolded:
            unfolded[-1] += raw_line[1:]
        else:
            unfolded.append(raw_line.rstrip())
    return unfolded
