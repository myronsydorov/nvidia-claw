"""Code generation: a triaged worry → an adapter plan + `run.py` (DESIGN §4 step 4).

The model answers with a ```json plan block (which adapters, with which
parameters, and how often to check) and a ```python block (run.py). The plan is
resolved through the adapter registry, so the adapters' own validation applies
(https only, no IP literals, exact paths). The permission-card `why` text is ours,
never the model's, and adapters may not name secrets beyond their fixed ones.
"""

import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from warden.adapters.base import Adapter
from warden.adapters.registry import ADAPTER_CATALOGUE, ADAPTER_FACTORIES, FIXED_ADAPTERS
from warden.compiler.guard import GUARD_RULE, untrusted
from warden.compiler.llm import Message
from warden.compiler.triage import Triage

MAX_ADAPTERS = 3
MIN_INTERVAL_S = 300
MAX_INTERVAL_S = 86400

# The parameters the model may give each factory adapter, and the permission-card
# `why` we attach. Fixed adapters take no parameters.
_FACTORY_PARAMS: dict[str, tuple[str, ...]] = {
    "transit_bvg": ("stop_id",),
    "web_diff": ("url",),
    "http_json": ("url",),  # no `secrets`: a watcher may not ask for arbitrary env secrets
    "rss": ("url",),
    "ics_calendar": ("url",),
}
_WHY: dict[str, str] = {
    "transit_bvg": "check departures for this stop",
    "web_diff": "check this page for changes",
    "http_json": "read this data",
    "rss": "read this feed for new items",
    "ics_calendar": "read this calendar",
}

# What run.py can call. Mirrors watcher_runtime.adapters.* and watcher_runtime.harness.
RUNTIME_API = """\
Harness (from watcher_runtime import harness):
  harness.emit(status, summary, source, data=None, next_check_s=3600, fear_came_true=None)
      Print the one result line. status: "ok" | "act_now" | "resolved" | "error".
      summary: <= 140 chars, plain, calm language. data: a small dict of evidence.
      Call it exactly once, as the last thing run.py does.
  harness.fail(summary)             -> emit an "error" result (use when the check itself failed)
  harness.now() -> datetime (UTC)   harness.parse_time(iso_str) -> datetime (UTC)
  harness.hours_until(iso_str_or_datetime) -> float
  harness.load_state() -> dict      harness.save_state(dict)   (persist between runs)

Adapters (from watcher_runtime.adapters import <name>); each has fetch(...) and parse(...):
  parcel_dhl.fetch(tracking_number: str) -> {"found": bool, "id", "status_code",
      "status", "description", "estimated_delivery", "delivered": bool}
      (the adapter handles its own API key; watchers never see secrets)
  transit_bvg.fetch(stop_id: str) -> {"departures": [{"line", "direction", "when",
      "delay_s", "platform", "cancelled": bool}]}   (stop_id: numeric BVG/VBB stop id)
  weather_openmeteo.fetch(latitude: float, longitude: float) -> {"current": {"time",
      "temperature_c", "precipitation_mm", "weather_code"}, "daily": [{"date" (YYYY-MM-DD),
      "temperature_max_c", "temperature_min_c", "precipitation_mm", "weather_code"}]}
      (7-day forecast; WMO weather codes: 51-67 and 80-82 rain, 71-77 snow, 95-99 storm)
  flight_status.fetch(icao24: str) -> {"found": bool, "callsign", "origin_country",
      "latitude", "longitude", "baro_altitude_m", "on_ground", "velocity_ms"}
      (icao24 is the aircraft's 24-bit hex transponder address, e.g. "3c6444")
  web_diff.fetch(url: str, previous=None) -> {"status": "no_baseline"|"unchanged"|"changed",
      "content_hash": str, "excerpt": str}
      To detect a change, call fetch(URL, None) and compare content_hash with the hash you
      saved via harness.save_state on the previous run (no saved hash = first run = "ok").
  http_json.fetch(url: str) -> dict (the JSON body; a non-object body is under "data")
  rss.fetch(url: str) -> {"items": [{"title", "link", "published", "guid"}]}
  ics_calendar.fetch(url: str) -> {"events": [{"uid", "summary", "location", "start", "end"}]}
"""

EXAMPLE = """\
```json
{"adapters": [{"name": "web_diff", "params": {"url": "https://www.example.org/tickets"}}],
 "interval_s": 3600}
```
```python
from watcher_runtime import harness
from watcher_runtime.adapters import web_diff

URL = "https://www.example.org/tickets"

try:
    page = web_diff.fetch(URL, None)
except Exception as exc:
    harness.fail("I couldn't read the ticket page just now.")
else:
    state = harness.load_state()
    previous = state.get("hash")
    harness.save_state({"hash": page["content_hash"]})
    if previous is not None and previous != page["content_hash"]:
        harness.emit("act_now", "The ticket page just changed. Have a look.", "example.org",
                     {"excerpt": page["excerpt"]}, next_check_s=3600)
    else:
        harness.emit("ok", "No change on the ticket page.", "example.org", next_check_s=3600)
```"""


def _catalogue() -> str:
    lines = []
    for info in ADAPTER_CATALOGUE.values():
        params = ", ".join(_FACTORY_PARAMS.get(info.name, ())) or "none"
        lines.append(f"- {info.name}: {info.description}. params: {params}")
    return "\n".join(lines)


SYSTEM = f"""You write watchers for Custody. A watcher is a short Python 3.12 script, run.py,
that checks ONE thing about a worry and prints one result via the harness. It runs in its own
locked-down sandbox that can only reach the endpoints of the adapters you choose.

Available adapters:
{_catalogue()}

{RUNTIME_API}
Hard rules (a static checker rejects anything else):
- Import ONLY `from watcher_runtime import harness` and
  `from watcher_runtime.adapters import <name>` for the adapters in your plan.
  No other imports at all: no os, sys, json, datetime, re, requests, httpx, subprocess.
- Use only the functions listed above. No eval/exec/getattr/open, no names or attributes
  starting with "_", no "__" anywhere.
- Every URL in the code must be exactly a URL from your plan (https only).
- Never put secrets, keys or tokens in the code; adapters handle their own credentials.
- Wrap fetches in try/except and call harness.fail(...) if the check could not be done.
- Call harness.emit or harness.fail exactly once per run.
- "ok" means the fear is not coming true right now (stay silent). "act_now" means the person
  must act now. "resolved" means the worry is settled either way (set fear_came_true).
  The first run has no saved state and must still emit "ok" or a real answer.
- Stay calm and brief in summaries. No "check again" suggestions.
- interval_s: 300..86400 seconds; check no more often than the worry needs.

Answer with exactly two fenced blocks, a ```json plan and a ```python run.py, like this:
{EXAMPLE}

{GUARD_RULE}"""


class PlanItem(BaseModel):
    name: str
    params: dict[str, Any] = Field(default_factory=dict)


class Plan(BaseModel):
    adapters: list[PlanItem] = Field(min_length=1, max_length=MAX_ADAPTERS)
    interval_s: int = 3600


@dataclass(frozen=True)
class Generated:
    adapters: list[Adapter]
    code: str
    interval_s: int


class CodegenError(Exception):
    """The answer could not be turned into a plan + code. The message is ours, safe to feed back."""


_BLOCK_RE = re.compile(r"```(json|python|py)[ \t]*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def parse_answer(content: str) -> tuple[Plan, str]:
    blocks: dict[str, str] = {}
    for lang, body in _BLOCK_RE.findall(content):
        key = "python" if lang.lower() in ("python", "py") else "json"
        blocks.setdefault(key, body)
    if "json" not in blocks or "python" not in blocks:
        raise CodegenError("the answer must contain one ```json plan block and one ```python block")
    try:
        plan = Plan.model_validate(json.loads(blocks["json"]))
    except (ValueError, ValidationError) as exc:
        raise CodegenError(f"the json plan is invalid ({type(exc).__name__})") from exc
    return plan, blocks["python"]


def resolve(plan: Plan) -> list[Adapter]:
    adapters: list[Adapter] = []
    for item in plan.adapters:
        if item.name in FIXED_ADAPTERS:
            if item.params:
                raise CodegenError(f"adapter {item.name} takes no params")
            adapters.append(FIXED_ADAPTERS[item.name])
        elif item.name in ADAPTER_FACTORIES:
            allowed = _FACTORY_PARAMS[item.name]
            extra = set(item.params) - set(allowed)
            missing = set(allowed) - set(item.params)
            if extra or missing:
                raise CodegenError(
                    f"adapter {item.name} takes exactly these params: {', '.join(allowed)}"
                )
            params = {k: str(item.params[k]) for k in allowed}
            try:
                adapters.append(ADAPTER_FACTORIES[item.name](**params, why=_WHY[item.name]))
            except (ValueError, ValidationError) as exc:
                # Our own validators' messages only (scheme, IP literal, stop id format).
                reason = str(exc).splitlines()[0][:200] if isinstance(exc, ValueError) else ""
                raise CodegenError(f"adapter {item.name} params rejected: {reason}") from exc
        else:
            raise CodegenError(f"unknown adapter {item.name!r}")
    names = [a.name for a in adapters]
    if len(set(names)) != len(names):
        raise CodegenError("each adapter may appear only once")
    return adapters


def build(content: str) -> Generated:
    plan, code = parse_answer(content)
    adapters = resolve(plan)
    interval = min(max(plan.interval_s, MIN_INTERVAL_S), MAX_INTERVAL_S)
    return Generated(adapters=adapters, code=code, interval_s=interval)


def first_messages(text: str, t: Triage, now: datetime) -> list[Message]:
    deadline = t.deadline.isoformat() if t.deadline else "none"
    return [
        Message("system", SYSTEM),
        Message(
            "user",
            f"Current time: {now.isoformat()}\n"
            f"Worry type: {t.type}. Deadline: {deadline}.\n"
            "The precise fear and the settling signal (from triage):\n"
            + untrusted(f"fear: {t.fear}\nsignal: {t.signal}", "triage_summary", max_chars=600)
            + "\nThe worry, as the user wrote it:\n"
            + untrusted(text, "worry_text")
            + "\nWrite the plan and run.py.",
        ),
    ]


def retry_messages(previous: list[Message], answer: str, feedback: str) -> list[Message]:
    return [
        *previous,
        Message("assistant", answer[:12000]),
        Message(
            "user",
            "That watcher was rejected. Fix it and answer again with both blocks.\n" + feedback,
        ),
    ]
