"""The person's own side of the "normal day" signal: check in, ask for help, and see exactly
what an allowed loved one asking "ok?" would get right now (before sharing rules)."""

from fastapi import APIRouter, Request, Response, status

from warden.models import ReassuranceAnswer
from warden.state import get_reassurance

router = APIRouter()


@router.post("/api/me/check-in", status_code=status.HTTP_204_NO_CONTENT)
async def check_in(request: Request) -> Response:
    await get_reassurance(request).check_in()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/api/me/help", status_code=status.HTTP_204_NO_CONTENT)
async def ask_for_help(request: Request) -> Response:
    await get_reassurance(request).set_help(True)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete("/api/me/help", status_code=status.HTTP_204_NO_CONTENT)
async def clear_help(request: Request) -> Response:
    await get_reassurance(request).set_help(False)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/api/me/signal")
async def my_signal(request: Request) -> ReassuranceAnswer:
    return await get_reassurance(request).current_signal()
