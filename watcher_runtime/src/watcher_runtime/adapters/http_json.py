"""Runtime helper for the http_json adapter — only calls the declared endpoint.

`fetch` GETs the one URL the adapter was declared with. `parse` is pure and
fixture-tested; `fetch` is not. `WatchResult.evidence.data` (warden.models) is a
dict, so a non-dict JSON body (a bare list or scalar) is wrapped under "data"
rather than passed through as-is.
"""

from typing import Any

import httpx2 as httpx


def fetch(url: str, headers: dict[str, str] | None = None) -> dict[str, Any]:
    with httpx.Client(timeout=10) as client:
        response = client.get(url, headers=headers or {})
        response.raise_for_status()
        result: dict[str, Any] = parse(response.json())
        return result


def parse(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    return {"data": raw}
