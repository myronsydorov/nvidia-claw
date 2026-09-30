"""Runtime helper for the parcel_dhl adapter — only calls the declared endpoint.

`fetch` hits GET https://api-eu.dhl.com/track/shipments (the declared endpoint's
exact path); the tracking number travels as a query parameter, never in the
path. `parse` is pure and fixture-tested; `fetch` is not.
"""

from typing import Any

import httpx2 as httpx

_BASE_URL = "https://api-eu.dhl.com"


def fetch(tracking_number: str, api_key: str) -> dict[str, Any]:
    with httpx.Client(base_url=_BASE_URL, timeout=10) as client:
        response = client.get(
            "/track/shipments",
            params={"trackingNumber": tracking_number},
            headers={"DHL-API-Key": api_key},
        )
        response.raise_for_status()
        result: dict[str, Any] = parse(response.json())
        return result


def parse(raw: dict[str, Any]) -> dict[str, Any]:
    """Summarize a DHL Unified Tracking API response into plain data."""
    shipments = raw.get("shipments") or []
    if not shipments:
        return {"found": False}
    shipment = shipments[0]
    status = shipment.get("status") or {}
    return {
        "found": True,
        "id": shipment.get("id"),
        "status_code": status.get("statusCode"),
        "status": status.get("status"),
        "description": status.get("description"),
        "estimated_delivery": shipment.get("estimatedTimeOfDelivery"),
        "delivered": status.get("statusCode") == "delivered",
    }
