import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from warden import db
from warden.auth import require_device_token
from warden.events import EventBus
from warden.routers import events, health, ledger, people, push, sharing_rules, worries
from warden.sandbox.factory import get_sandbox_driver
from warden.scheduler import LogPushNotifier, Scheduler, SystemClock


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.events = EventBus()
    app.state.driver = get_sandbox_driver()
    async with db.lifespan(app):
        if os.environ.get("WARDEN_SCHEDULER") == "off":
            yield
            return
        scheduler = Scheduler(
            app.state.store, app.state.driver, app.state.events, SystemClock(), LogPushNotifier()
        )
        task = asyncio.create_task(scheduler.run_forever())
        try:
            yield
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(
    title="Custody Warden",
    lifespan=lifespan,
    dependencies=[Depends(require_device_token)],
    # security-reviewer (T-07): docs/openapi/redoc would otherwise be the only
    # unauthenticated routes on the whole app, exposing the full schema if this
    # port is ever reachable beyond loopback.
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)

app.include_router(health.router)
app.include_router(worries.router)
app.include_router(people.router)
app.include_router(sharing_rules.router)
app.include_router(ledger.router)
app.include_router(events.router)
app.include_router(push.router)
