"""Runtime helper for the web_diff adapter — only calls the declared endpoint.

`fetch` GETs the one URL the adapter was declared with. `parse` is pure and
fixture-tested; `fetch` is not. There is no baseline to diff against on a
watcher's first run — `parse(None, current)` reports that honestly instead of
guessing "changed". Content is compared as whitespace-normalized text, a
deliberately simple heuristic (no HTML-aware diffing); it can false-positive on
pages with e.g. embedded timestamps.
"""

import hashlib
from typing import Any, Literal

import httpx2 as httpx

DiffStatus = Literal["no_baseline", "unchanged", "changed"]


def fetch(url: str, previous: str | None) -> dict[str, Any]:
    with httpx.Client(timeout=10) as client:
        response = client.get(url)
        response.raise_for_status()
        result: dict[str, Any] = parse(previous, response.text)
        return result


def parse(previous: str | None, current: str) -> dict[str, Any]:
    current_hash = _content_hash(current)
    status: DiffStatus
    if previous is None:
        status = "no_baseline"
    elif _content_hash(previous) == current_hash:
        status = "unchanged"
    else:
        status = "changed"
    return {"status": status, "content_hash": current_hash, "excerpt": _excerpt(current)}


def _content_hash(text: str) -> str:
    normalized = " ".join(text.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _excerpt(text: str, limit: int = 140) -> str:
    return " ".join(text.split())[:limit]
