import asyncio
import contextlib
import os
from collections.abc import AsyncIterator, Coroutine
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI

from warden import db
from warden.auth import require_device_token
from warden.compiler import Compiler
from warden.compiler.llm import llm_from_env
from warden.events import EventBus
from warden.mcp_server import mount as mount_mcp
from warden.mcp_server import running as mcp_running
from warden.reassurance.keys import key_path_from_env, load_or_create
from warden.reassurance.relay_client import RelayClient
from warden.reassurance.service import Reassurance
from warden.reassurance.sources import NoProbe, probe_from_env
from warden.routers import (
    events,
    health,
    ledger,
    me,
    pairing,
    people,
    push,
    sharing_rules,
    worries,
)
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
        # Layer 2 (T-14/T-15). Without RELAY_URL, pairing/asking answer 503 and nothing polls.
        relay_url = os.environ.get("RELAY_URL")
        relay = RelayClient(relay_url) if relay_url else None
        probe = probe_from_env()
        reassurance = Reassurance(
            app.state.store,
            app.state.events,
            load_or_create(key_path_from_env()),
            relay,
            probe,
            ask_timeout_s=float(os.environ.get("WARDEN_ASK_TIMEOUT_S", "20")),
            ask_cooldown_s=float(os.environ.get("WARDEN_ASK_COOLDOWN_S", "600")),
            poll_s=float(os.environ.get("WARDEN_RELAY_POLL_S", "2")),
        )
        app.state.reassurance = reassurance
        if relay is not None:
            _spawn(app, reassurance.run_forever())
        if not isinstance(probe, NoProbe):
            _spawn(app, reassurance.run_sampler_forever())
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
            # The brain's MCP tools (T-11); a mounted app's own lifespan never runs.
            async with mcp_running(app):
                yield
        finally:
            tasks: set[asyncio.Task[None]] = app.state.background_tasks
            if scheduler_task is not None:
                tasks.add(scheduler_task)
            for task in list(tasks):
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task
            if relay is not None:
                await relay.aclose()


def _spawn(app: FastAPI, coro: Coroutine[Any, Any, None]) -> None:
    task = asyncio.create_task(coro)
    app.state.background_tasks.add(task)
    task.add_done_callback(app.state.background_tasks.discard)


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
app.include_router(pairing.router)
app.include_router(me.router)
# /mcp: the brain's tools (CONTRACTS §4), behind WARDEN_MCP_TOKEN; no approval tool.
mount_mcp(app)
