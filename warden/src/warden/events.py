import asyncio
import json
from collections.abc import AsyncGenerator

from warden.models import Event, EventType


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[Event]] = set()

    def subscribe(self) -> asyncio.Queue[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue()
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[Event]) -> None:
        self._subscribers.discard(queue)

    async def publish(self, event_type: EventType, data: dict[str, object]) -> None:
        event = Event(type=event_type, data=data)
        for queue in list(self._subscribers):
            await queue.put(event)

    async def stream(self) -> AsyncGenerator[str, None]:
        queue = self.subscribe()
        try:
            while True:
                event = await queue.get()
                yield f"event: {event.type}\ndata: {json.dumps(event.data)}\n\n"
        finally:
            self.unsubscribe(queue)
