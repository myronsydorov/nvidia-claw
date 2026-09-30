"""Runtime helper for the weather_openmeteo adapter — only calls the declared endpoint.

`fetch` hits GET https://api.open-meteo.com/v1/forecast (the declared endpoint's
exact path); latitude/longitude travel as query parameters. `parse` is pure and
fixture-tested; `fetch` is not.
"""

from typing import Any

import httpx2 as httpx

_BASE_URL = "https://api.open-meteo.com"


def fetch(latitude: float, longitude: float) -> dict[str, Any]:
    with httpx.Client(base_url=_BASE_URL, timeout=10) as client:
        response = client.get(
            "/v1/forecast",
            params={
                "latitude": latitude,
                "longitude": longitude,
                "current": "temperature_2m,precipitation,weather_code",
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,weather_code",
                "timezone": "auto",
            },
        )
        response.raise_for_status()
        result: dict[str, Any] = parse(response.json())
        return result


def parse(raw: dict[str, Any]) -> dict[str, Any]:
    """Summarize an Open-Meteo forecast response into plain data."""
    current = raw.get("current") or {}
    daily = raw.get("daily") or {}
    days = daily.get("time") or []
    daily_summary = [
        {
            "date": days[i],
            "temperature_max_c": (daily.get("temperature_2m_max") or [None] * len(days))[i],
            "temperature_min_c": (daily.get("temperature_2m_min") or [None] * len(days))[i],
            "precipitation_mm": (daily.get("precipitation_sum") or [None] * len(days))[i],
            "weather_code": (daily.get("weather_code") or [None] * len(days))[i],
        }
        for i in range(len(days))
    ]
    return {
        "current": {
            "time": current.get("time"),
            "temperature_c": current.get("temperature_2m"),
            "precipitation_mm": current.get("precipitation"),
            "weather_code": current.get("weather_code"),
        },
        "daily": daily_summary,
    }
