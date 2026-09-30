"""Runtime helper for the rss adapter — only calls the declared endpoint.

`fetch` GETs the one feed URL the adapter was declared with. `parse` is pure and
fixture-tested; `fetch` is not.

Honest limits: this is an RSS-2.0-only parser (no Atom support) using the
standard library's xml.etree.ElementTree, which per Python's own docs is not
hardened against XML entity-expansion ("billion laughs") attacks. The feed is
untrusted content (AGENTS.md invariant #6) fetched inside the watcher's own
OpenShell sandbox (ADR-0001) — a malicious feed can waste that sandbox's CPU/
memory, not escape it or reach anything else. Swap in `defusedxml` before this
adapter is trusted with feeds from sources a person hasn't vetted.
"""

from typing import Any
from xml.etree import ElementTree

import httpx2 as httpx


def fetch(url: str) -> dict[str, Any]:
    with httpx.Client(timeout=10) as client:
        response = client.get(url)
        response.raise_for_status()
        result: dict[str, Any] = parse(response.text)
        return result


def parse(raw_xml: str) -> dict[str, Any]:
    """Extract title/link/pubDate/guid per <item> from an RSS 2.0 document."""
    root = ElementTree.fromstring(raw_xml)
    items = []
    for item in root.findall("./channel/item"):
        items.append(
            {
                "title": _text(item, "title"),
                "link": _text(item, "link"),
                "published": _text(item, "pubDate"),
                "guid": _text(item, "guid"),
            }
        )
    return {"items": items}


def _text(item: ElementTree.Element, tag: str) -> str | None:
    element = item.find(tag)
    return element.text if element is not None else None
