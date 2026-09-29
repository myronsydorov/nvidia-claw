from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request, status

from warden.models import (
    AskPeerRequest,
    AskPeerResponse,
    Peer,
    PeopleListItem,
    PrivacyReceipt,
    ReassuranceAnswer,
)
from warden.state import get_events, get_store

router = APIRouter()


@router.get("/api/people")
async def list_people(request: Request) -> list[PeopleListItem]:
    store = get_store(request)
    rows = await store.peers.query()
    items = []
    for row in rows:
        peer = Peer.model_validate(row["peer"])
        last_answer = (
            ReassuranceAnswer.model_validate(row["last_answer"]) if row.get("last_answer") else None
        )
        items.append(
            PeopleListItem(
                peer=peer, last_answer=last_answer, last_answer_at=row.get("last_answer_at")
            )
        )
    return items


@router.post("/api/people/{peer_id}/ask")
async def ask_peer(peer_id: str, body: AskPeerRequest, request: Request) -> AskPeerResponse:
    store = get_store(request)
    row = await store.peers.get(peer_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="peer not found")

    # No relay/crypto yet (T-14/T-15): an honest fixed-vocabulary placeholder, not a real answer.
    now = datetime.now(UTC)
    answer = ReassuranceAnswer(level="unknown", reason="not_enough_data", ts=now)
    receipt = PrivacyReceipt(
        bytes_sent=0, fields_shared=[], location_shared=False, egress_log_ref="n/a (no relay yet)"
    )

    row["last_answer"] = answer.model_dump(mode="json")
    row["last_answer_at"] = now.isoformat()
    await store.peers.put(peer_id, row)

    await get_events(request).publish("peer.answer", {"peer_id": peer_id, "q": body.q})
    return AskPeerResponse(answer=answer, receipt=receipt)
