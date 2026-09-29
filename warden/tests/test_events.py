import asyncio
import contextlib
from collections.abc import AsyncGenerator

import httpx2 as httpx
from warden.app import app
from warden.events import EventBus
from warden.routers.events import stream_events


class _StateStub:
    def __init__(self, events: EventBus) -> None:
        self.events = events


class _AppStub:
    def __init__(self, events: EventBus) -> None:
        self.state = _StateStub(events)


class _RequestStub:
    def __init__(self, events: EventBus) -> None:
        self.app = _AppStub(events)


async def test_events_requires_auth() -> None:
    # A 401 short-circuits before the streaming route ever runs, so this one
    # completes normally and is safe to exercise through the real ASGI transport.
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            response = await client.get("/api/events")
    assert response.status_code == 401


async def test_bus_delivers_a_published_event_to_a_subscriber() -> None:
    bus = EventBus()
    queue = bus.subscribe()
    await bus.publish("worry.updated", {"worry_id": "w_x"})
    event = await asyncio.wait_for(queue.get(), timeout=1)
    assert event.type == "worry.updated"
    assert event.data == {"worry_id": "w_x"}


async def test_bus_delivers_to_every_subscriber() -> None:
    bus = EventBus()
    a, b = bus.subscribe(), bus.subscribe()
    await bus.publish("peer.answer", {"peer_id": "p_x"})
    got_a = await asyncio.wait_for(a.get(), timeout=1)
    got_b = await asyncio.wait_for(b.get(), timeout=1)
    assert got_a.type == got_b.type == "peer.answer"


async def test_bus_stream_unsubscribes_when_the_consumer_stops() -> None:
    bus = EventBus()
    gen = bus.stream()
    reader: asyncio.Task[str] = asyncio.create_task(gen.__anext__())
    await asyncio.sleep(0)  # let the generator reach subscribe() + block on queue.get()
    assert len(bus._subscribers) == 1

    reader.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await reader
    assert len(bus._subscribers) == 0


async def test_stream_events_route_reads_from_app_state_event_bus() -> None:
    # StreamingResponse's body_iterator is bus.stream() itself; ASGITransport can't
    # stream an infinite generator (it buffers the whole app call), so drive it directly.
    bus = EventBus()
    response = await stream_events(_RequestStub(bus))  # type: ignore[arg-type]
    assert response.media_type == "text/event-stream"

    body_iterator: AsyncGenerator[str, None] = response.body_iterator  # type: ignore[assignment]
    reader: asyncio.Task[str] = asyncio.create_task(body_iterator.__anext__())
    await asyncio.sleep(0)  # let the generator reach subscribe() + block on queue.get()
    await bus.publish("worry.updated", {"worry_id": "w_x"})

    chunk = await asyncio.wait_for(reader, timeout=1)
    assert chunk == 'event: worry.updated\ndata: {"worry_id": "w_x"}\n\n'
