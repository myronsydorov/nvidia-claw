"""Weather forecast for a location — api.open-meteo.com, no API key required.

Latitude/longitude travel as query parameters at runtime
(watcher_runtime.adapters.weather_openmeteo.fetch), never in the declared path.
"""

from warden.adapters.base import Adapter, Endpoint

ADAPTER = Adapter(
    name="weather_openmeteo",
    endpoints=[
        Endpoint(
            host="api.open-meteo.com",
            path="/v1/forecast",
            why="check the weather forecast",
        )
    ],
    description="Check the weather forecast for a location (Open-Meteo, no API key required)",
)
