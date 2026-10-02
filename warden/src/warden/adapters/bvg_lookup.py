"""Resolve a stop *name* to a real BVG/VBB stop id at compile time (S7 incident, 2026-10-02).

The model once wrote `/stops/8011120/departures` from memory: BVG answers that id with
`NOT_FOUND`, every dry run failed, and the worry was parked. A stop id now only ever comes
from this lookup (or, verbatim, from the person's own words): the Warden asks BVG's
`/locations` endpoint, takes the first real stop that serves the requested line, and pins its
id into the declared path (and so into the policy and the permission card).

The Warden makes this one read-only GET to a fixed public host; watchers still only run in
their own sandbox (AGENTS #1).
"""

import asyncio
import json
import logging
import os
import re
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import httpx2 as httpx

log = logging.getLogger(__name__)

BASE_URL = "https://v6.bvg.transport.rest"
_STOP_ID = re.compile(r"[0-9]{6,12}")

# Stop-lookup incident (2026-10-02, 08:17 Berlin): BVG's hosted API answered 503 after its own
# 10 s upstream timeout, three hand-overs in a row. One attempt is bounded, transient failures
# (transport errors, timeouts, 429, 5xx) are retried twice with backoff, and a resolved stop is
# cached on disk so it never needs the network again.
TIMEOUT = httpx.Timeout(8.0, connect=4.0)
BACKOFF_S = (1.0, 3.0)  # sleeps before retry 1 and retry 2

Fetch = Callable[[str, dict[str, str]], Awaitable[Any]]
Sleep = Callable[[float], Awaitable[None]]


async def http_fetch(path: str, params: dict[str, str]) -> Any:
    async with httpx.AsyncClient(base_url=BASE_URL, timeout=TIMEOUT) as client:
        response = await client.get(path, params=params)
        response.raise_for_status()
        return response.json()


# Swapped for a fixture-backed stub in unit tests (no live network there).
fetch: Fetch = http_fetch
sleep: Sleep = asyncio.sleep


def _transient(exc: Exception) -> bool:
    if isinstance(exc, httpx.HTTPStatusError):
        code = exc.response.status_code
        return code == 429 or code >= 500
    return isinstance(exc, httpx.TransportError)


async def _fetch_with_retries(path: str, params: dict[str, str]) -> Any:
    for attempt in range(len(BACKOFF_S) + 1):
        try:
            return await fetch(path, params)
        except (httpx.HTTPError, ValueError) as exc:
            reason = _reason(exc)
            if attempt == len(BACKOFF_S) or not _transient(exc):
                log.warning("bvg stop lookup failed: %s (attempt %d)", reason, attempt + 1)
                raise StopLookupError(reason) from None
            log.info("bvg stop lookup: %s, retrying (attempt %d)", reason, attempt + 1)
            await sleep(BACKOFF_S[attempt])
    raise AssertionError("unreachable")


def _reason(exc: Exception) -> str:
    if isinstance(exc, httpx.HTTPStatusError):
        return f"HTTP {exc.response.status_code}"
    return type(exc).__name__


def cache_path() -> Path:
    """Next to the Warden DB unless `WARDEN_STOP_CACHE` says otherwise."""
    explicit = os.environ.get("WARDEN_STOP_CACHE")
    if explicit:
        return Path(explicit)
    db = Path(os.environ.get("WARDEN_DB_PATH", "warden.db"))
    return db.parent / "bvg_stops.json"


def _cache_key(query: str, line: str | None) -> str:
    return f"{' '.join(query.split()).casefold()}|{(line or '').upper()}"


def _cache_read() -> dict[str, dict[str, Any]]:
    try:
        raw = json.loads(cache_path().read_text())
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def _cached(query: str, line: str | None) -> "Stop | None":
    cache = _cache_read()
    entry = cache.get(_cache_key(query, line))
    if entry is None and line is None:
        # No line asked for: a stop found for the same name with any line is still that stop.
        prefix = _cache_key(query, None)
        entry = next((v for k, v in sorted(cache.items()) if k.startswith(prefix)), None)
    if not isinstance(entry, dict):
        return None
    stop_id, name, lines = entry.get("id"), entry.get("name"), entry.get("lines")
    if not (isinstance(stop_id, str) and _STOP_ID.fullmatch(stop_id) and isinstance(name, str)):
        return None
    if not isinstance(lines, list) or not all(isinstance(x, str) for x in lines):
        return None
    return Stop(id=stop_id, name=name, lines=tuple(lines))


def _remember(query: str, line: str | None, stop: "Stop") -> None:
    """Best effort: a cache that can't be written only costs a network call next time."""
    path = cache_path()
    data = _cache_read()
    data[_cache_key(query, line)] = asdict(stop) | {"lines": list(stop.lines)}
    tmp = path.with_suffix(".tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps(data, indent=1, sort_keys=True))
        os.replace(tmp, path)
    except OSError as exc:
        log.warning("bvg stop cache not written: %s", type(exc).__name__)


@dataclass(frozen=True)
class Stop:
    id: str
    name: str
    lines: tuple[str, ...]


class StopLookupError(Exception):
    """The lookup service could not be reached; the caller treats it as a build failure."""


async def find_stop(query: str, line: str | None = None) -> Stop | None:
    """The best matching stop for `query` that serves `line` (if given), or None.

    A stop found once is answered from the on-disk cache from then on. "Not found" is not
    cached: the person may fix a typo, and BVG may add the stop.
    """
    hit = _cached(query, line)
    if hit is not None:
        return hit
    raw = await _fetch_with_retries(
        "/locations",
        {"query": query, "results": "8", "poi": "false", "addresses": "false",
         "linesOfStops": "true"},
    )  # fmt: skip
    if not isinstance(raw, list):
        raise StopLookupError("unexpected answer")
    for item in raw:
        if not isinstance(item, dict) or item.get("type") != "stop":
            continue
        stop_id = str(item.get("id", ""))
        if not _STOP_ID.fullmatch(stop_id):
            continue
        lines = tuple(
            dict.fromkeys(
                str(entry["name"])
                for entry in item.get("lines") or []
                if isinstance(entry, dict) and entry.get("name")
            )
        )
        if line is not None and line.upper() not in {name.upper() for name in lines}:
            continue
        stop = Stop(id=stop_id, name=str(item.get("name", "")), lines=lines)
        _remember(query, line, stop)
        return stop
    return None
