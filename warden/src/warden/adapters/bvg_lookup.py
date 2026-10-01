"""Resolve a stop *name* to a real BVG/VBB stop id at compile time (S7 incident, 2026-10-02).

The model once wrote `/stops/8011120/departures` from memory: BVG answers that id with
`NOT_FOUND`, every dry run failed, and the worry was parked. A stop id now only ever comes
from this lookup (or, verbatim, from the person's own words): the Warden asks BVG's
`/locations` endpoint, takes the first real stop that serves the requested line, and pins its
id into the declared path (and so into the policy and the permission card).

The Warden makes this one read-only GET to a fixed public host; watchers still only run in
their own sandbox (AGENTS #1).
"""

import re
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import httpx2 as httpx

BASE_URL = "https://v6.bvg.transport.rest"
_STOP_ID = re.compile(r"[0-9]{6,12}")

Fetch = Callable[[str, dict[str, str]], Awaitable[Any]]


async def http_fetch(path: str, params: dict[str, str]) -> Any:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=15) as client:
        response = await client.get(path, params=params)
        response.raise_for_status()
        return response.json()


# Swapped for a fixture-backed stub in unit tests (no live network there).
fetch: Fetch = http_fetch


@dataclass(frozen=True)
class Stop:
    id: str
    name: str
    lines: tuple[str, ...]


class StopLookupError(Exception):
    """The lookup service could not be reached; the caller treats it as a build failure."""


async def find_stop(query: str, line: str | None = None) -> Stop | None:
    """The best matching stop for `query` that serves `line` (if given), or None."""
    try:
        raw = await fetch(
            "/locations",
            {"query": query, "results": "8", "poi": "false", "addresses": "false",
             "linesOfStops": "true"},
        )  # fmt: skip
    except (httpx.HTTPError, ValueError) as exc:
        raise StopLookupError(type(exc).__name__) from None
    if not isinstance(raw, list):
        raise StopLookupError("unexpected answer")
    for item in raw:
        if not isinstance(item, dict) or item.get("type") != "stop":
            continue
        stop_id = str(item.get("id", ""))
        if not _STOP_ID.fullmatch(stop_id):
            continue
        lines = tuple(
            str(entry.get("name")) for entry in item.get("lines") or [] if isinstance(entry, dict)
        )
        if line is not None and line.upper() not in {name.upper() for name in lines}:
            continue
        return Stop(id=stop_id, name=str(item.get("name", "")), lines=lines)
    return None
