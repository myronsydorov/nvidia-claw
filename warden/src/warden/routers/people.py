from fastapi import APIRouter, HTTPException, Request, Response, status

from warden.models import (
    AskPeerRequest,
    AskPeerResponse,
    PeopleListItem,
    ReassuranceAnswer,
)
from warden.reassurance.service import (
    BadAnswer,
    NoAnswer,
    PeerNotFound,
    RelayUnavailable,
    TooSoon,
)
from warden.state import get_reassurance, get_store

router = APIRouter()


@router.get("/api/people")
async def list_people(request: Request) -> list[PeopleListItem]:
    store = get_store(request)
    reassurance = get_reassurance(request)
    rows = await store.peers.query()
    items = []
    for row in rows:
        peer = reassurance.peer_from_row(row)
        last_answer = (
            ReassuranceAnswer.model_validate(row["last_answer"]) if row.get("last_answer") else None
        )
        items.append(
            PeopleListItem(
                peer=peer,
                last_answer=last_answer,
                last_answer_at=row.get("last_answer_at"),
                last_asked_at=row.get("last_asked_at"),
            )
        )
    return items


@router.post("/api/people/{peer_id}/ask")
async def ask_peer(peer_id: str, body: AskPeerRequest, request: Request) -> AskPeerResponse:
    try:
        return await get_reassurance(request).ask(peer_id, body.q)
    except PeerNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "peer not found") from exc
    except RelayUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    except NoAnswer as exc:
        raise HTTPException(status.HTTP_504_GATEWAY_TIMEOUT, str(exc)) from exc
    except BadAnswer as exc:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(exc)) from exc
    except TooSoon as exc:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, str(exc)) from exc


@router.post("/api/people/{peer_id}/confirm", status_code=status.HTTP_204_NO_CONTENT)
async def confirm(peer_id: str, request: Request) -> Response:
    """The fingerprints matched: the peer's sharing rule takes effect."""
    try:
        await get_reassurance(request).confirm(peer_id)
    except PeerNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "peer not found") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/api/people/{peer_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unpair(peer_id: str, request: Request) -> Response:
    """E.g. when the fingerprints on the two screens don't match."""
    try:
        await get_reassurance(request).unpair(peer_id)
    except PeerNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "peer not found") from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
