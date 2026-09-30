"""Runtime helper for the transit_bvg adapter — only calls the declared endpoint.

`fetch` hits GET https://v6.bvg.transport.rest/stops/{stop_id}/departures (the
declared endpoint's exact path, per warden.adapters.transit_bvg.declare). `parse`
is pure and fixture-tested; `fetch` is not.
"""

from typing import Any

import httpx2 as httpx

_BASE_URL = "https://v6.bvg.transport.rest"


def fetch(stop_id: str) -> dict[str, Any]:
    with httpx.Client(base_url=_BASE_URL, timeout=10) as client:
        response = client.get(f"/stops/{stop_id}/departures")
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
                "when": entry.get("when"),
                "delay_s": entry.get("delay"),
                "platform": entry.get("platform"),
                "cancelled": bool(entry.get("cancelled", False)),
            }
        )
    return {"departures": departures}
