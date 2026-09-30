"""Stand-in compiler for local dev and the T-12 e2e test (CUSTODY_COMPILER=mock).

Walks a new worry triaging -> compiling -> awaiting_approval with a canned,
keyword-picked watcher so the app's hand-over flow runs against a real Warden.
T-09's real compiler (triage, codegen against adapters, generated policy, dry
run) replaces this module. It never touches the sandbox driver: sandboxes are
only created on approve.
"""

import asyncio
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from warden.db import Store
from warden.events import EventBus
from warden.ids import new_watcher_id
from warden.models import PermissionLine, TimelineEvent, Watcher, Worry, WorryStatus, WorryType


def enabled() -> bool:
    return os.environ.get("CUSTODY_COMPILER") == "mock"


def _step_s() -> float:
    return float(os.environ.get("CUSTODY_MOCK_COMPILE_S", "0.8"))


@dataclass(frozen=True)
class _Template:
    keywords: tuple[str, ...]
    type: WorryType
    fear: str
    adapter: str
    line: PermissionLine
    interval_s: int


# Mirrors app/src/mocks/fixtures.ts `templates`. Exact hosts and paths, GET only.
_TEMPLATES = (
    _Template(
        keywords=("parcel", "package", "dhl", "delivery"),
        type="deadline",
        fear="Parcel not delivered in time",
        adapter="parcel_dhl",
        line=PermissionLine(
            method="GET",
            host="api-eu.dhl.com",
            path="/track/shipments",
            why="check the parcel's status",
        ),
        interval_s=3600,
    ),
    _Template(
        keywords=("train", "bvg", "bus", "tram", "s-bahn"),
        type="checkable",
        fear="The train is cancelled",
        adapter="transit_bvg",
        line=PermissionLine(
            method="GET",
            host="v6.bvg.transport.rest",
            path="/stops/900100001/departures",
            why="see the departures",
        ),
        interval_s=1800,
    ),
    _Template(
        keywords=("weather", "rain", "storm", "wind", "snow"),
        type="deadline",
        fear="Bad weather on the day",
        adapter="weather_openmeteo",
        line=PermissionLine(
            method="GET",
            host="api.open-meteo.com",
            path="/v1/forecast",
            why="read the forecast",
        ),
        interval_s=10800,
    ),
)
_FALLBACK = _TEMPLATES[0]


def pick_template(text: str) -> _Template:
    lower = text.lower()
    for t in _TEMPLATES:
        if any(k in lower for k in t.keywords):
            return t
    return _FALLBACK


def policy_yaml(sandbox_name: str, line: PermissionLine) -> str:
    return (
        "network_policies:\n"
        f"  {sandbox_name}:\n"
        "    endpoints:\n"
        f"      - host: {line.host}\n"
        "        port: 443\n"
        "        protocol: rest\n"
        "        enforcement: enforce\n"
        "        rules:\n"
        f'          - allow: {{ method: GET, path: "{line.path}" }}\n'
        "    binaries:\n"
        "      - path: /usr/bin/python3.12\n"
    )


async def _load(store: Store, worry_id: str) -> tuple[Worry, list[TimelineEvent]] | None:
    row = await store.worries.get(worry_id)
    if row is None:
        return None
    return (
        Worry.model_validate(row["worry"]),
        [TimelineEvent.model_validate(e) for e in row["timeline"]],
    )


async def _save(store: Store, worry: Worry, timeline: list[TimelineEvent]) -> None:
    row: dict[str, Any] = {
        "worry": worry.model_dump(mode="json"),
        "timeline": [t.model_dump(mode="json") for t in timeline],
    }
    await store.worries.put(worry.id, row, status=worry.status)


async def mock_compile(store: Store, events: EventBus, worry_id: str) -> None:
    template = None
    steps: tuple[tuple[WorryStatus, WorryStatus], ...] = (
        ("triaging", "compiling"),
        ("compiling", "awaiting_approval"),
    )
    for expected, step in steps:
        await asyncio.sleep(_step_s())
        loaded = await _load(store, worry_id)
        # The user may have let it go meanwhile; never resurrect it.
        if loaded is None or loaded[0].status != expected:
            return
        worry, timeline = loaded
        now = datetime.now(UTC)

        if step == "compiling":
            template = pick_template(worry.text)
            worry.type = template.type
            worry.fear = template.fear
            timeline.append(TimelineEvent(at=now, kind="triaged", text="Understood what to watch."))
        else:
            assert template is not None
            watcher_id = new_watcher_id()
            sandbox_name = f"cw-{watcher_id[-8:].lower()}"
            watcher = Watcher(
                id=watcher_id,
                worry_id=worry.id,
                adapters=[template.adapter],
                code="# mock compiler: no watcher code until T-09\n",
                policy_yaml=policy_yaml(sandbox_name, template.line),
                policy_summary=[template.line],
                sandbox_name=sandbox_name,
                interval_s=template.interval_s,
                state="awaiting_approval",
                last_result=None,
            )
            await store.watchers.put(
                watcher.id, watcher.model_dump(mode="json"), worry_id=worry.id, state=watcher.state
            )
            worry.watcher_id = watcher.id
            timeline.append(TimelineEvent(at=now, kind="compiled", text="Wrote a watcher."))
            timeline.append(
                TimelineEvent(at=now, kind="approval_requested", text="Asked for your permission.")
            )

        worry.status = step
        worry.updated_at = now
        await _save(store, worry, timeline)
        await events.publish("worry.updated", {"worry_id": worry.id})

    await events.publish("approval.needed", {"worry_id": worry_id})
