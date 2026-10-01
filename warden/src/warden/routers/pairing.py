from fastapi import APIRouter, HTTPException, Request, status

from warden.models import (
    PairingJoinRequest,
    PairingStartRequest,
    PairingStartResponse,
    PairingStatusResponse,
    Peer,
)
from warden.reassurance.service import (
    AlreadyPaired,
    InvalidCode,
    PairingNotFound,
    RelayUnavailable,
    SelfPairing,
)
from warden.state import get_reassurance

router = APIRouter()


@router.post("/api/pairing")
async def start_pairing(body: PairingStartRequest, request: Request) -> PairingStartResponse:
    try:
        return await get_reassurance(request).start_pairing(body.display_name)
    except RelayUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc


@router.get("/api/pairing/{pairing_id}")
async def pairing_status(pairing_id: str, request: Request) -> PairingStatusResponse:
    return await get_reassurance(request).pairing_status(pairing_id)


@router.post("/api/pairing/join")
async def join_pairing(body: PairingJoinRequest, request: Request) -> Peer:
    try:
        return await get_reassurance(request).join_pairing(body.code, body.display_name)
    except InvalidCode as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    except PairingNotFound as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, str(exc)) from exc
    except (SelfPairing, AlreadyPaired) as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, str(exc)) from exc
    except RelayUnavailable as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
