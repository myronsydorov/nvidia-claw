from fastapi import APIRouter, Request

from warden.models import LedgerResponse
from warden.state import get_store

router = APIRouter()


@router.get("/api/ledger")
async def get_ledger(request: Request) -> LedgerResponse:
    store = get_store(request)

    resolved = await store.worries.query(status="resolved")
    never_needed_you = 0
    needed_you = 0
    for row in resolved:
        came_true = row["worry"].get("fear_came_true")
        if came_true is True:
            needed_you += 1
        elif came_true is False:
            never_needed_you += 1

    return LedgerResponse(
        worries_total=await store.worries.count(),
        active=await store.worries.count(status="watching"),
        never_needed_you=never_needed_you,
        needed_you=needed_you,
        # CONTRACTS §5: the fraction (0–1) of closed worries with a known outcome whose fear
        # came true; 0.0 while no outcome is known (the app then shows "No outcomes yet").
        came_true_rate=needed_you / known if (known := needed_you + never_needed_you) else 0.0,
        # Still honest zeros: these need data the scheduler doesn't record yet.
        median_warning_lead_h=0.0,
        came_true_by_type={},
        watchers_built=await store.watchers.count(),
        sandboxes_live=await store.sandboxes_live(),
        endpoints_denied=0,
        peer_questions_answered=await store.questions_log.count(),
    )
