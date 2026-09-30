"""The `worries` table row shape, `{worry, timeline}`, shared by the routes and the scheduler."""

from typing import Any

from warden.db import Store
from warden.models import TimelineEvent, Watcher, Worry


def parse_row(row: dict[str, Any]) -> tuple[Worry, list[TimelineEvent]]:
    worry = Worry.model_validate(row["worry"])
    timeline = [TimelineEvent.model_validate(e) for e in row["timeline"]]
    return worry, timeline


async def save_worry(store: Store, worry: Worry, timeline: list[TimelineEvent]) -> dict[str, Any]:
    row = {
        "worry": worry.model_dump(mode="json"),
        "timeline": [t.model_dump(mode="json") for t in timeline],
    }
    await store.worries.put(worry.id, row, status=worry.status)
    return row


async def save_watcher(store: Store, watcher: Watcher) -> None:
    await store.watchers.put(
        watcher.id, watcher.model_dump(mode="json"), worry_id=watcher.worry_id, state=watcher.state
    )
