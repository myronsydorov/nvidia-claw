"""BVG (Berlin transit) departures for one stop — v6.bvg.transport.rest.

Fixed host, parameterized path: the real API embeds the stop ID in the path
itself, so we bake one exact literal path per watcher rather than declaring a
`/stops/` prefix (which would expose every sibling /stops/* sub-resource, not
just departures for this stop).
"""

import re

from warden.adapters.base import Adapter, Endpoint

_HOST = "v6.bvg.transport.rest"
_STOP_ID_PATTERN = re.compile(r"^[0-9]+$")


def declare(*, stop_id: str, why: str = "check departures for this stop") -> Adapter:
    if not _STOP_ID_PATTERN.match(stop_id):
        raise ValueError(f"stop_id must be numeric, got {stop_id!r}")
    return Adapter(
        name="transit_bvg",
        endpoints=[
            Endpoint(host=_HOST, path=f"/stops/{stop_id}/departures", why=why),
        ],
        description="Check BVG (Berlin transit) departures and disruptions for a stop",
    )
