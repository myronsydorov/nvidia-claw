from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status

from warden.db import Store
from warden.ids import new_worry_id
from warden.models import (
    OutcomeRequest,
    TimelineEvent,
    Watcher,
    WatchResult,
    Worry,
    WorryCreateRequest,
    WorryDetail,
    WorrySummary,
)
from warden.state import get_driver, get_events, get_store
from warden.worry_rows import save_watcher, save_worry

router = APIRouter()


def _now() -> datetime:
    return datetime.now(UTC)


async def _row(store: Store, worry_id: str) -> dict[str, Any]:
    row = await store.worries.get(worry_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="worry not found")
    return row


async def _detail(store: Store, row: dict[str, Any]) -> WorryDetail:
    worry = Worry.model_validate(row["worry"])
    watcher = None
    if worry.watcher_id is not None:
        watcher_data = await store.watchers.get(worry.watcher_id)
        watcher = Watcher.model_validate(watcher_data) if watcher_data else None
    timeline = [TimelineEvent.model_validate(e) for e in row["timeline"]]
    return WorryDetail(worry=worry, watcher=watcher, timeline=timeline)


async def _require_awaiting_approval(store: Store, worry: Worry) -> Watcher:
    if worry.watcher_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="no watcher for this worry"
        )
    watcher_data = await store.watchers.get(worry.watcher_id)
    if watcher_data is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="no watcher for this worry"
        )
    watcher = Watcher.model_validate(watcher_data)
    if watcher.state != "awaiting_approval":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"watcher is {watcher.state!r}, not awaiting_approval",
        )
    return watcher


@router.post("/api/worries", status_code=status.HTTP_201_CREATED)
async def create_worry(body: WorryCreateRequest, request: Request) -> Worry:
    store = get_store(request)
    now = _now()
    worry = Worry(
        id=new_worry_id(),
        text=body.text,
        type="unclassified",
        fear="",
        deadline=None,
        status="triaging",
        watcher_id=None,
        resolution=None,
        fear_came_true=None,
        created_at=now,
        updated_at=now,
    )
    timeline = [TimelineEvent(at=now, kind="created", text="You handed it over.")]
    await save_worry(store, worry, timeline)
    await get_events(request).publish("worry.updated", {"worry_id": worry.id})
    return worry


@router.get("/api/worries")
async def list_worries(
    request: Request, status_filter: str | None = Query(None, alias="status")
) -> list[WorrySummary]:
    store = get_store(request)
    filters = {"status": status_filter} if status_filter else {}
    rows = await store.worries.query(**filters)
    summaries = []
    for row in rows:
        worry = Worry.model_validate(row["worry"])
        last_result = None
        if worry.watcher_id is not None:
            watcher_data = await store.watchers.get(worry.watcher_id)
            if watcher_data and watcher_data.get("last_result"):
                last_result = WatchResult.model_validate(watcher_data["last_result"])
        summaries.append(WorrySummary(worry=worry, last_result=last_result))
    return summaries


@router.get("/api/worries/{worry_id}")
async def get_worry(worry_id: str, request: Request) -> WorryDetail:
    store = get_store(request)
    return await _detail(store, await _row(store, worry_id))


@router.post("/api/worries/{worry_id}/approve")
async def approve_worry(worry_id: str, request: Request) -> WorryDetail:
    store = get_store(request)
    async with store.write_lock:
        row = await _row(store, worry_id)
        worry = Worry.model_validate(row["worry"])
        watcher = await _require_awaiting_approval(store, worry)

        driver = get_driver(request)
        await driver.create(watcher.sandbox_name, image="watcher-base")
        await driver.apply_policy(watcher.sandbox_name, watcher.policy_yaml)
        watcher.state = "active"

        now = _now()
        worry.status = "watching"
        worry.updated_at = now
        timeline = [TimelineEvent.model_validate(e) for e in row["timeline"]]
        timeline.append(
            TimelineEvent(at=now, kind="approved", text="You allowed it. Watching quietly.")
        )

        await save_watcher(store, watcher)
        row = await save_worry(store, worry, timeline)
        await get_events(request).publish("worry.updated", {"worry_id": worry.id})
        return await _detail(store, row)


@router.post("/api/worries/{worry_id}/deny")
async def deny_worry(worry_id: str, request: Request) -> WorryDetail:
    store = get_store(request)
    async with store.write_lock:
        row = await _row(store, worry_id)
        worry = Worry.model_validate(row["worry"])
        watcher = await _require_awaiting_approval(store, worry)
        watcher.state = "retired"

        now = _now()
        worry.status = "parked"
        worry.updated_at = now
        timeline = [TimelineEvent.model_validate(e) for e in row["timeline"]]
        timeline.append(TimelineEvent(at=now, kind="denied", text="You said no."))

        await save_watcher(store, watcher)
        row = await save_worry(store, worry, timeline)
        await get_events(request).publish("worry.updated", {"worry_id": worry.id})
        return await _detail(store, row)


@router.post("/api/worries/{worry_id}/let-go")
async def let_go_worry(worry_id: str, request: Request) -> WorryDetail:
    store = get_store(request)
    async with store.write_lock:
        row = await _row(store, worry_id)
        worry = Worry.model_validate(row["worry"])

        now = _now()
        worry.status = "resolved"
        worry.updated_at = now
        timeline = [TimelineEvent.model_validate(e) for e in row["timeline"]]
        timeline.append(TimelineEvent(at=now, kind="let_go", text="You let it go."))

        if worry.watcher_id is not None:
            watcher_data = await store.watchers.get(worry.watcher_id)
            if watcher_data is not None:
                watcher = Watcher.model_validate(watcher_data)
                if watcher.state in ("active", "paused"):  # a paused watcher keeps its sandbox
                    try:
                        await get_driver(request).delete(watcher.sandbox_name)
                    except KeyError:
                        pass  # already gone (e.g. driver state lost across a restart)
                watcher.state = "retired"
                await save_watcher(store, watcher)

        row = await save_worry(store, worry, timeline)
        await get_events(request).publish("worry.updated", {"worry_id": worry.id})
        return await _detail(store, row)


@router.post("/api/worries/{worry_id}/outcome")
async def record_outcome(worry_id: str, body: OutcomeRequest, request: Request) -> WorryDetail:
    store = get_store(request)
    async with store.write_lock:
        row = await _row(store, worry_id)
        worry = Worry.model_validate(row["worry"])
        if worry.status != "resolved":
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT, detail="worry is not resolved yet"
            )
        worry.fear_came_true = body.fear_came_true
        worry.updated_at = _now()
        timeline = [TimelineEvent.model_validate(e) for e in row["timeline"]]

        row = await save_worry(store, worry, timeline)
        await get_events(request).publish("worry.updated", {"worry_id": worry.id})
        return await _detail(store, row)
