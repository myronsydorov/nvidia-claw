"""Catalogue of built adapters, seeding T-09's future compiler catalogue prompt.

`FIXED_ADAPTERS` holds bucket-A `Adapter` constants (no worry-specific params
needed). `ADAPTER_FACTORIES` holds bucket-B/C `declare(...)` callables — T-09's
compiler will call these with worry-specific arguments (a stop ID, a URL, ...).
`ADAPTER_CATALOGUE` is the flat, worry-agnostic description of both, for
prompting an LLM to pick which adapter(s) a watcher should use.
"""

from collections.abc import Callable
from dataclasses import dataclass

from warden.adapters import (
    flight_status,
    http_json,
    ics_calendar,
    parcel_dhl,
    rss,
    transit_bvg,
    weather_openmeteo,
    web_diff,
)
from warden.adapters.base import Adapter


@dataclass(frozen=True, slots=True)
class AdapterInfo:
    name: str
    description: str
    secrets: tuple[str, ...]
    parameters: tuple[str, ...]  # () for fixed; ("stop_id",) or ("url",) for factories


FIXED_ADAPTERS: dict[str, Adapter] = {
    "parcel_dhl": parcel_dhl.ADAPTER,
    "weather_openmeteo": weather_openmeteo.ADAPTER,
    "flight_status": flight_status.ADAPTER,
}

ADAPTER_FACTORIES: dict[str, Callable[..., Adapter]] = {
    "transit_bvg": transit_bvg.declare,
    "web_diff": web_diff.declare,
    "http_json": http_json.declare,
    "rss": rss.declare,
    "ics_calendar": ics_calendar.declare,
}

ADAPTER_CATALOGUE: dict[str, AdapterInfo] = {
    "parcel_dhl": AdapterInfo(
        name="parcel_dhl",
        description=parcel_dhl.ADAPTER.description,
        secrets=tuple(parcel_dhl.ADAPTER.secrets),
        parameters=(),
    ),
    "weather_openmeteo": AdapterInfo(
        name="weather_openmeteo",
        description=weather_openmeteo.ADAPTER.description,
        secrets=tuple(weather_openmeteo.ADAPTER.secrets),
        parameters=(),
    ),
    "transit_bvg": AdapterInfo(
        name="transit_bvg",
        description="Check BVG (Berlin transit) departures and disruptions for a stop",
        secrets=(),
        parameters=("stop_id",),
    ),
    "web_diff": AdapterInfo(
        name="web_diff",
        description="Fetch a specific web page and detect meaningful changes since the last check",
        secrets=(),
        parameters=("url",),
    ),
    "http_json": AdapterInfo(
        name="http_json",
        description="Fetch a JSON endpoint and evaluate a condition against the response",
        secrets=(),  # worry-specific secret names are supplied per declare() call, not fixed here
        parameters=("url", "secrets"),
    ),
    "flight_status": AdapterInfo(
        name="flight_status",
        description=flight_status.ADAPTER.description,
        secrets=tuple(flight_status.ADAPTER.secrets),
        parameters=(),
    ),
    "rss": AdapterInfo(
        name="rss",
        description="Check an RSS/Atom feed for new items",
        secrets=(),
        parameters=("url",),
    ),
    "ics_calendar": AdapterInfo(
        name="ics_calendar",
        description="Check an ICS calendar feed for new or changed events",
        secrets=(),
        parameters=("url",),
    ),
}
