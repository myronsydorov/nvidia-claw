"""Talk to Custody (CONTRACTS §3 `/api/talk`) and the brain's daily close (CONTRACTS §6).

App → Warden → loopback OpenClaw chat endpoint → brain → MCP tools. The Warden never acts on
what the brain says; replies are plain text for the person. A worry with a link still goes
through `POST /api/worries`, so the person sees exactly what will be read (THREAT_MODEL A12).
"""

import logging
import time
from datetime import UTC, datetime

from fastapi import APIRouter, HTTPException, Request

from warden.brain import (
    REPLY_MAX,
    TALK_SYSTEM,
    URLISH,
    Brain,
    BrainUnavailable,
    TalkLimiter,
    clean,
    without_links,
)
from warden.checks import local_tz
from warden.daily_close import NoteNotConfirmed, close_lock, latest_close, write_close
from warden.models import DailyClose, TalkReply, TalkRequest
from warden.state import get_store

router = APIRouter()
log = logging.getLogger(__name__)

TALK_SESSION = "custody-app"  # + the local date: one brain session per day, not forever
CLOSE_MIN_GAP_S = 600


def _brain(request: Request) -> Brain:
    brain: Brain | None = getattr(request.app.state, "brain", None)
    if brain is None:
        raise HTTPException(503, "Custody's brain isn't connected right now.")
    return brain


def _limiter(request: Request) -> TalkLimiter:
    limiter: TalkLimiter | None = getattr(request.app.state, "talk_limiter", None)
    if limiter is None:
        limiter = request.app.state.talk_limiter = TalkLimiter()
    return limiter


@router.post("/api/talk")
async def talk(body: TalkRequest, request: Request) -> TalkReply:
    text = body.text.strip()
    if not text:
        raise HTTPException(422, "Say something first.")
    if URLISH.search(text):
        raise HTTPException(
            422,
            "Worries with a link go through Hand over, so you see exactly what will be read.",
        )
    brain = _brain(request)
    limiter = _limiter(request)
    if not limiter.allow(time.monotonic()):
        raise HTTPException(429, "One moment: let's take this slowly.")
    limiter.busy = True
    try:
        session = f"{TALK_SESSION}-{datetime.now(local_tz()).date().isoformat()}"
        reply = await brain.chat(session, TALK_SYSTEM, text)
    except BrainUnavailable as exc:
        log.warning("talk: brain unavailable", extra={"error": str(exc)})
        raise HTTPException(503, "I couldn't reach Custody's brain just now.") from None
    finally:
        limiter.busy = False
    return TalkReply(reply=clean(without_links(reply), REPLY_MAX), at=datetime.now(UTC))


@router.get("/api/daily-close")
async def get_daily_close(request: Request) -> DailyClose | None:
    return await latest_close(get_store(request))


@router.post("/api/daily-close")
async def post_daily_close(request: Request) -> DailyClose:
    store = get_store(request)
    brain = _brain(request)
    # Every attempt counts toward the gap (a failed one too), and one at a time.
    last_attempt: float | None = getattr(request.app.state, "close_attempt_at", None)
    if last_attempt is not None and time.monotonic() - last_attempt < CLOSE_MIN_GAP_S:
        raise HTTPException(429, "Today's close was written a few minutes ago.")
    request.app.state.close_attempt_at = time.monotonic()
    try:
        async with close_lock(request.app):
            return await write_close(store, brain, datetime.now(UTC))
    except BrainUnavailable:
        raise HTTPException(503, "I couldn't reach Custody's brain just now.") from None
    except NoteNotConfirmed:
        raise HTTPException(502, "The note named a number the tools didn't confirm.") from None
