from typing import Any

from fastapi import APIRouter, Request

from warden.models import LedgerResponse
from warden.state import get_store

router = APIRouter()


def is_build_failure(row: dict[str, Any]) -> bool:
    kinds = {event["kind"] for event in row["timeline"]}
    return row["worry"]["status"] == "failed" or ("failed" in kinds and "approved" not in kinds)


def is_test(row: dict[str, Any]) -> bool:
    """Created to test the system (scripts/mark_test_worry.py), not one of the person's worries."""
    return any(event["kind"] == "test" for event in row["timeline"])


@router.get("/api/ledger")
async def get_ledger(request: Request) -> LedgerResponse:
    store = get_store(request)

    # Build failures don't count (S7 incident): a worry whose watcher never got built is not a
    # worry Custody held. A watcher paused after errors was approved, so it still counts.
    # Test worries don't count either (CONTRACTS §5), nor do their watchers.
    rows = await store.worries.query()
    counted = [row for row in rows if not is_build_failure(row) and not is_test(row)]
    test_ids = {row["worry"]["id"] for row in rows if is_test(row)}
    never_needed_you = 0
    needed_you = 0
    for row in (r for r in counted if r["worry"]["status"] == "resolved"):
        came_true = row["worry"].get("fear_came_true")
        if came_true is True:
            needed_you += 1
        elif came_true is False:
            never_needed_you += 1

    return LedgerResponse(
        worries_total=len(counted),
        active=sum(1 for r in counted if r["worry"]["status"] == "watching"),
        never_needed_you=never_needed_you,
        needed_you=needed_you,
        # CONTRACTS §5: the fraction (0–1) of closed worries with a known outcome whose fear
        # came true; 0.0 while no outcome is known (the app then shows "No outcomes yet").
        came_true_rate=needed_you / known if (known := needed_you + never_needed_you) else 0.0,
        # Still honest zeros: these need data the scheduler doesn't record yet.
        median_warning_lead_h=0.0,
        came_true_by_type={},
        # A dry_run_failed row (kept before 2026-10-02) was never built.
        watchers_built=sum(
            1
            for w in await store.watchers.query()
            if w["state"] != "dry_run_failed" and w["worry_id"] not in test_ids
        ),
        sandboxes_live=await store.sandboxes_live(),
        endpoints_denied=0,
        peer_questions_answered=await store.questions_log.count(),
    )
