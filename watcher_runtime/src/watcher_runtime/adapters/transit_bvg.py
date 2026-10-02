"""Runtime helper for the transit_bvg adapter — only calls the declared endpoint.

`fetch` hits GET https://v6.bvg.transport.rest/stops/{stop_id}/departures (the
declared endpoint's exact path, per warden.adapters.transit_bvg.declare). `parse`
is pure and fixture-tested; `fetch` is not.
"""

from typing import Any

import httpx2 as httpx

_BASE_URL = "https://v6.bvg.transport.rest"


def fetch(stop_id: str, when: str | None = None, duration_min: int | None = None) -> dict[str, Any]:
    """Departures from now (the next few minutes), or from `when` (ISO time with an offset)
    for `duration_min` minutes (1..180), e.g. to cover a trip later today. The query string
    isn't part of the declared path, so the policy is unchanged."""
    params: dict[str, str] = {"results": "200"}
    if when is not None:
        params["when"] = str(when)
    if duration_min is not None:
        params["duration"] = str(max(1, min(int(duration_min), 180)))
    with httpx.Client(base_url=_BASE_URL, timeout=15) as client:
        response = client.get(f"/stops/{stop_id}/departures", params=params)
        response.raise_for_status()
        result: dict[str, Any] = parse(response.json())
        return result


def parse(raw: dict[str, Any]) -> dict[str, Any]:
    """Summarize a v6.bvg.transport.rest departures response into plain data."""
    departures = []
    for entry in raw.get("departures", []):
        line = entry.get("line") or {}
        departures.append(
            {
                "line": line.get("name"),
                "direction": entry.get("direction"),
                # A cancelled departure has no `when`; fall back to the planned time.
                "when": entry.get("when") or entry.get("plannedWhen"),
                "planned_when": entry.get("plannedWhen"),
                # null means "no realtime data": 0, so `delay_s > 60` never crashes a watcher.
                "delay_s": int(entry.get("delay") or 0),
                "platform": entry.get("platform"),
                "cancelled": bool(entry.get("cancelled", False)),
            }
        )
    return {"departures": departures}


# The default a transit worry gets unless it says otherwise (2026-10-02): last night's S7
# watcher would have alerted on any delay over 1 minute, in either direction. That is noise.
DEFAULT_MIN_DELAY_MIN = 10


def _place(name: str) -> str:
    """'S Potsdam Hauptbahnhof' and 'Potsdam Hbf' compare equal; so do 'S+U' prefixes."""
    words = name.casefold().replace("(berlin)", " ").replace("+", " ").replace("-", " ").split()
    short = {"hauptbahnhof": "hbf", "bahnhof": "bhf", "bf": "bhf", "str.": "str", "straße": "str"}
    words = [short.get(w, w) for w in words if w not in {"s", "u"}]
    return " ".join(words)


def disruptions(
    data: dict[str, Any],
    line: str,
    toward: str | None = None,
    min_delay_min: int = DEFAULT_MIN_DELAY_MIN,
) -> dict[str, Any]:
    """Departures of `line` heading `toward` that are cancelled or at least `min_delay_min`
    minutes late. `toward` is the direction shown on the board (the line's end station, e.g.
    "Potsdam Hbf"); None means both directions. Returns {"matched": n, "disrupted": [...]}:
    `matched` = departures of that line and direction, so 0 means the board had none to judge
    (a wrong direction name, or no trains in the window), which is not the same as "all fine".
    """
    want_line = line.strip().upper()
    want_dir = _place(toward) if toward else ""
    threshold_s = max(1, int(min_delay_min)) * 60
    matched = 0
    disrupted: list[dict[str, Any]] = []
    for dep in data.get("departures", []):
        if str(dep.get("line") or "").upper() != want_line:
            continue
        direction = _place(str(dep.get("direction") or ""))
        if want_dir and want_dir not in direction and direction not in want_dir:
            continue
        matched += 1
        if dep.get("cancelled") or int(dep.get("delay_s") or 0) >= threshold_s:
            disrupted.append(
                {
                    "line": dep.get("line"),
                    "direction": dep.get("direction"),
                    "planned_when": dep.get("planned_when"),
                    "delay_min": int(dep.get("delay_s") or 0) // 60,
                    "cancelled": bool(dep.get("cancelled")),
                }
            )
    return {"matched": matched, "disrupted": disrupted}
