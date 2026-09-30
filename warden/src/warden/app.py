import asyncio
import contextlib
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI

from warden import db
from warden.auth import require_device_token
from warden.compiler import Compiler
from warden.compiler.llm import llm_from_env
from warden.events import EventBus
from warden.routers import events, health, ledger, people, push, sharing_rules, worries
from warden.sandbox.factory import get_sandbox_driver
from warden.scheduler import LogPushNotifier, Scheduler, SystemClock


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.events = EventBus()
    app.state.driver = get_sandbox_driver()
    app.state.background_tasks = set()  # compile tasks (T-09); scheduler joins on shutdown too
    llm = llm_from_env()  # fails fast on CUSTODY_LLM_REPLAY without mock sandboxes
    async with db.lifespan(app):
        app.state.compiler = None
        if os.environ.get("WARDEN_COMPILER") != "off":  # route tests drive state themselves
            compiler = Compiler(app.state.store, app.state.events, app.state.driver, llm)
            app.state.compiler = compiler
            # A restart (or `--reload`) cancels in-flight compiles; pick them up again.
            for worry_id in await compiler.stranded():
                resumed = asyncio.create_task(compiler.compile_worry(worry_id))
                app.state.background_tasks.add(resumed)
                resumed.add_done_callback(app.state.background_tasks.discard)
        scheduler_task: asyncio.Task[None] | None = None
        if os.environ.get("WARDEN_SCHEDULER") != "off":
            scheduler = Scheduler(
                app.state.store,
                app.state.driver,
                app.state.events,
                SystemClock(),
                LogPushNotifier(),
            )
            scheduler_task = asyncio.create_task(scheduler.run_forever())
        try:
            yield
        finally:
            tasks: set[asyncio.Task[None]] = app.state.background_tasks
            if scheduler_task is not None:
                tasks.add(scheduler_task)
            for task in list(tasks):
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
