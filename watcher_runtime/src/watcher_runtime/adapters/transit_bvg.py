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
