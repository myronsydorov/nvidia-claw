"""Check a flight's current state — opensky-network.org, no API key for
anonymous/basic (rate-limited) use.

The flight's icao24 transponder code travels as a runtime query parameter
(watcher_runtime.adapters.flight_status.fetch), never in the declared path.
"""

from warden.adapters.base import Adapter, Endpoint

ADAPTER = Adapter(
    name="flight_status",
    endpoints=[
        Endpoint(
            host="opensky-network.org",
            path="/api/states/all",
            why="check flight status",
        )
    ],
    description="Check a flight's current state (OpenSky Network, anonymous access)",
)
