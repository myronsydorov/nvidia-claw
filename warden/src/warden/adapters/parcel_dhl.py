"""Track a DHL shipment by tracking number — api-eu.dhl.com.

The exact AdapterDeclaration shown in docs/CONTRACTS.md §1. The tracking number
is a runtime query parameter (watcher_runtime.adapters.parcel_dhl.fetch), never
part of the declared path, so the policy never needs to know it.
"""

from warden.adapters.base import Adapter, Endpoint

ADAPTER = Adapter(
    name="parcel_dhl",
    endpoints=[
        Endpoint(
            host="api-eu.dhl.com",
            path="/track/shipments",
            why="check parcel status",
        )
    ],
    secrets=["DHL_API_KEY"],
    description="Track a DHL shipment by tracking number",
)
