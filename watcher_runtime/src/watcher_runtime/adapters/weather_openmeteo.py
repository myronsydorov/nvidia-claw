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
                # Hour by hour for the next two days, so a watcher can check "16:00-19:00".
                "hourly": "precipitation,precipitation_probability,weather_code",
                "forecast_hours": 48,
                "timezone": "Europe/Berlin",
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
    # Open-Meteo gives local wall-clock times without an offset; add it, so every time a watcher
    # compares is unambiguous (the S7 incident was a time-zone mix-up).
    offset_s = int(raw.get("utc_offset_seconds") or 0)
    sign = "-" if offset_s < 0 else "+"
    offset = f"{sign}{abs(offset_s) // 3600:02d}:{abs(offset_s) % 3600 // 60:02d}"
    hourly = raw.get("hourly") or {}
    hours = hourly.get("time") or []

    def column(name: str) -> list[Any]:
        values = hourly.get(name) or []
        return values if len(values) == len(hours) else [None] * len(hours)

    hourly_summary = [
        {"time": f"{t}{offset}", "precipitation_mm": mm, "precipitation_probability": p,
         "weather_code": code}
        for t, mm, p, code in zip(
            hours, column("precipitation"), column("precipitation_probability"),
            column("weather_code"), strict=True,
        )
    ]  # fmt: skip
    return {
        "hourly": hourly_summary,
        "current": {
            "time": current.get("time"),
            "temperature_c": current.get("temperature_2m"),
            "precipitation_mm": current.get("precipitation"),
            "weather_code": current.get("weather_code"),
        },
        "daily": daily_summary,
    }
