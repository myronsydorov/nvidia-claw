from fastapi import APIRouter, Request, Response, status

from warden.models import PushSubscription
from warden.state import get_store

router = APIRouter()


@router.post("/api/push/subscribe", status_code=status.HTTP_204_NO_CONTENT)
async def subscribe(body: PushSubscription, request: Request) -> Response:
    store = get_store(request)
    await store.push_subscriptions.put(body.endpoint, body.model_dump(mode="json"))
    return Response(status_code=status.HTTP_204_NO_CONTENT)
