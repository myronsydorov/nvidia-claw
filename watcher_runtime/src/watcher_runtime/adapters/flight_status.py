"""Runtime helper for the flight_status adapter — only calls the declared endpoint.

`fetch` hits GET https://opensky-network.org/api/states/all (the declared
endpoint's exact path), filtered server-side to one icao24 transponder code via
a query parameter. `parse` is pure and fixture-tested; `fetch` is not.
"""

from typing import Any

import httpx2 as httpx

_BASE_URL = "https://opensky-network.org"

# OpenSky state-vector field order: https://openskynetwork.github.io/opensky-api/rest.html
_ICAO24, _CALLSIGN, _ORIGIN_COUNTRY = 0, 1, 2
_LONGITUDE, _LATITUDE, _BARO_ALTITUDE, _ON_GROUND, _VELOCITY = 5, 6, 7, 8, 9


def fetch(icao24: str) -> dict[str, Any]:
    with httpx.Client(base_url=_BASE_URL, timeout=10) as client:
        response = client.get("/api/states/all", params={"icao24": icao24})
        response.raise_for_status()
        result: dict[str, Any] = parse(response.json())
        return result


def parse(raw: dict[str, Any]) -> dict[str, Any]:
    """Summarize the (at most one, since fetch filters by icao24) matching
    OpenSky state vector into plain data."""
    states = raw.get("states") or []
    if not states:
        return {"found": False}
    state = states[0]
    return {
        "found": True,
        "icao24": state[_ICAO24],
        "callsign": (state[_CALLSIGN] or "").strip() or None,
        "origin_country": state[_ORIGIN_COUNTRY],
        "longitude": state[_LONGITUDE],
        "latitude": state[_LATITUDE],
        "baro_altitude_m": state[_BARO_ALTITUDE],
        "on_ground": state[_ON_GROUND],
        "velocity_ms": state[_VELOCITY],
    }
