from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse

from warden.state import get_events

router = APIRouter()


@router.get("/api/events")
async def stream_events(request: Request) -> StreamingResponse:
    return StreamingResponse(get_events(request).stream(), media_type="text/event-stream")
