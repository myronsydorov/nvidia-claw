from fastapi import APIRouter, HTTPException, Request, status

from warden.models import (
    AskPeerRequest,
    AskPeerResponse,
    Peer,
    PeopleListItem,
    ReassuranceAnswer,
)
from warden.reassurance.service import BadAnswer, NoAnswer, PeerNotFound, RelayUnavailable
from warden.state import get_reassurance, get_store

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
