from fastapi import APIRouter, Request

from warden.models import HealthResponse
from warden.state import get_store

router = APIRouter()


@router.get("/api/health")
async def health(request: Request) -> HealthResponse:
    sandboxes_live = await get_store(request).sandboxes_live()
    return HealthResponse(status="ok", sandboxes_live=sandboxes_live)
