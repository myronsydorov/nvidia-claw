"""Code generation: a triaged worry → an adapter plan + `run.py` (DESIGN §4 step 4).

The model answers with a ```json plan block (which adapters, with which
parameters, and how often to check) and a ```python block (run.py). The plan is
resolved through the adapter registry, so the adapters' own validation applies
(https only, no IP literals, exact paths). The permission-card `why` text is ours,
never the model's, and adapters may not name secrets beyond their fixed ones.
"""

import ast
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, ValidationError

from warden.adapters.base import Adapter
from warden.adapters.registry import ADAPTER_CATALOGUE, ADAPTER_FACTORIES, FIXED_ADAPTERS
from warden.compiler.guard import GUARD_RULE, untrusted
from warden.compiler.llm import Message
from warden.compiler.triage import LOCAL_TZ, Triage

MAX_ADAPTERS = 3
MIN_INTERVAL_S = 300
MAX_INTERVAL_S = 86400

# transit_bvg: the model names the stop as the person wrote it; the Warden resolves the real id
# (adapters.bvg_lookup) and swaps it in for this placeholder in run.py. It never writes an id.
STOP_PLACEHOLDER = "BVG_STOP_ID"

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
  transit_bvg.fetch(stop_id: str, when=None, duration_min=None) -> {"departures": [{"line",
      "direction", "when", "planned_when", "delay_s" (int, 0 if unknown), "platform",
      "cancelled": bool}]}
      Write STOP_ID = "BVG_STOP_ID" exactly; the Warden puts in the real stop id. Without
      `when` you get the next few minutes only; to cover a later trip pass when=<ISO UTC time
      to start from> and duration_min=<1..180>. Times are ISO strings with an offset.
  transit_bvg.disruptions(data, line: str, toward: str | None = None, min_delay_min=10)
      -> {"matched": int, "disrupted": [{"line", "direction", "planned_when", "delay_min",
      "cancelled"}]}. Always judge departures with this. Defaults, unless the worry says
      otherwise: only the person's direction of travel (toward = the end station shown on
      the board for their direction, e.g. "Potsdam Hbf" for an S7 from Lichtenberg to Potsdam),
      and only cancellations or delays of 10 minutes or more (keep min_delay_min=10 unless
      the worry names another number). "matched" == 0 means the board had no such
      departures to judge (wrong direction name, or no trains in the window): call
      harness.fail, never "act_now" and never a silent "ok".
  weather_openmeteo.fetch(latitude: float, longitude: float) -> {"hourly": [{"time" (ISO,
      Berlin time with offset), "precipitation_mm", "precipitation_probability" (0-100),
      "weather_code"}] (next 48 hours), "current": {"time", "temperature_c",
      "precipitation_mm", "weather_code"}, "daily": [{"date" (YYYY-MM-DD),
      "temperature_max_c", "temperature_min_c", "precipitation_mm", "weather_code"}]}
      (7-day daily forecast; WMO weather codes: 51-67 and 80-82 rain, 71-77 snow, 95-99
      storm; for a time window use "hourly" and compare with harness.parse_time)
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


_PROMPT_PARAMS = {
    "transit_bvg": 'stop (the stop name exactly as the person wrote it), line (e.g. "S7"; '
    "optional)",
}


def _catalogue() -> str:
    lines = []
    for info in ADAPTER_CATALOGUE.values():
        params = _PROMPT_PARAMS.get(info.name) or ", ".join(_FACTORY_PARAMS.get(info.name, ()))
        params = params or "none"
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
- Times the person gives are Europe/Berlin local time; the deadline you get is already UTC.
- Never invent a URL, tracking number, stop id or transponder code (BVG stops: give the stop
  name in the plan and use STOP_ID = "BVG_STOP_ID" in run.py). If the worry lacks one the
  adapter needs, answer ONLY with a json block naming that adapter, and no python block:
  ```json
  {{"adapters": [], "missing": "ics_calendar"}}
  ```

Answer with exactly two fenced blocks, a ```json plan and a ```python run.py, like this:
{EXAMPLE}

{GUARD_RULE}"""


class PlanItem(BaseModel):
    name: str
    params: dict[str, Any] = Field(default_factory=dict)


class Plan(BaseModel):
    adapters: list[PlanItem] = Field(default_factory=list, max_length=MAX_ADAPTERS)
    interval_s: int = 3600
    missing: str | None = None  # the adapter whose input (URL, tracking number...) is absent


@dataclass(frozen=True)
class Generated:
    adapters: list[Adapter]
    code: str
    interval_s: int


class CodegenError(Exception):
    """The answer could not be turned into a plan + code. The message is ours, safe to feed back."""


# What to ask the person for, per adapter. Our words, never the model's (they reach the app).
_ASK: dict[str, str] = {
    "ics_calendar": "Send me the link to the calendar and I'll watch it.",
    "web_diff": "Send me the link to the page and I'll watch it.",
    "rss": "Send me the link to the feed and I'll watch it.",
    "http_json": "Send me the link to the data and I'll watch it.",
    "parcel_dhl": "Send me the tracking number and I'll watch it.",
    "transit_bvg": "I couldn't find that stop. Tell me its exact name (as on the BVG app) "
    "and I'll watch it.",
    "flight_status": "Send me the plane's transponder code (ICAO24) and I'll watch it.",
    "weather_openmeteo": "Tell me the place and I'll watch the forecast.",
}
_ASK_DEFAULT = "Tell me exactly what to check (a link or a number) and I'll watch it."


class MissingInput(Exception):
    """The worry lacks what an adapter needs. Retrying can't help: ask the person instead."""

    def __init__(self, adapter: str) -> None:
        super().__init__(f"missing input for {adapter}")
        self.adapter = adapter
        self.reason = _ASK.get(adapter, _ASK_DEFAULT)


_BLOCK_RE = re.compile(r"```(json|python|py)[ \t]*\n(.*?)```", re.DOTALL | re.IGNORECASE)


def parse_answer(content: str) -> tuple[Plan, str]:
    blocks: dict[str, str] = {}
    for lang, body in _BLOCK_RE.findall(content):
        key = "python" if lang.lower() in ("python", "py") else "json"
        blocks.setdefault(key, body)
    if "json" not in blocks:
        raise CodegenError("the answer must contain one ```json plan block and one ```python block")
    try:
        plan = Plan.model_validate(json.loads(blocks["json"]))
    except (ValueError, ValidationError) as exc:
        raise CodegenError(f"the json plan is invalid ({type(exc).__name__})") from exc
    if plan.missing is not None:
        raise MissingInput(plan.missing)
    if not plan.adapters:
        raise CodegenError("the json plan has no adapters")
    if "python" not in blocks:
        raise CodegenError("the answer must contain one ```json plan block and one ```python block")
    return plan, blocks["python"]


TRANSIT_DEFAULT_MIN_DELAY = 10


def _check_transit_defaults(plan: Plan, code: str, worry_text: str) -> None:
    """Transit default (2026-10-02): only the direction of travel, only cancellations or delays
    of 10+ minutes, unless the worry says otherwise. Last night's S7 watcher alerted on any
    delay over 1 minute in either direction. Judging goes through transit_bvg.disruptions."""
    if not any(item.name == "transit_bvg" for item in plan.adapters):
        return
    try:
        tree = ast.parse(code)
    except SyntaxError:
        return  # the gate reports it
    calls = [
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "disruptions"
    ]
    if not calls:
        raise CodegenError(
            "judge the departures with transit_bvg.disruptions(data, line, toward=<the end "
            "station of the person's direction>) - defaults: their direction only, and only "
            "cancellations or delays of 10 minutes or more"
        )
    numbers = {int(n) for n in re.findall(r"\d+", worry_text)}
    for call in calls:
        if len(call.args) > 2:
            raise CodegenError(
                "pass toward= and min_delay_min= to transit_bvg.disruptions by keyword"
            )
        for kw in call.keywords:
            if kw.arg != "min_delay_min":
                continue
            value = kw.value
            if not (isinstance(value, ast.Constant) and isinstance(value.value, int)):
                raise CodegenError("min_delay_min must be a whole number literal")
            if value.value < TRANSIT_DEFAULT_MIN_DELAY and value.value not in numbers:
                raise CodegenError(
                    f"keep min_delay_min={TRANSIT_DEFAULT_MIN_DELAY}: the worry names no "
                    "smaller delay"
                )


def _check_inputs_given(plan: Plan, worry_text: str) -> None:
    """Every URL in the plan must come from the worry itself; an invented one means it's missing."""
    for item in plan.adapters:
        url = item.params.get("url")
        if item.name not in _FACTORY_PARAMS or "url" not in _FACTORY_PARAMS[item.name]:
            continue
        if not isinstance(url, str):
            continue  # resolve() reports the missing param
        parts = urlsplit(url.strip())
        where = f"{parts.hostname or ''}{parts.path}".rstrip("/").lower()
        if not where or where not in worry_text.lower():
            raise MissingInput(item.name)


MAX_STOP_QUERY_CHARS = 80


def stop_queries(content: str, worry_text: str) -> list[tuple[str, str | None]]:
    """The (stop name, line) pairs a plan asks the Warden to look up; [] if none or unparseable.

    Only names the person actually wrote (and short ones) leave the host: the model can't make
    the Warden send arbitrary text to BVG (T-11/S7 security review)."""
    try:
        plan, _ = parse_answer(content)
    except (CodegenError, MissingInput):
        return []
    queries = []
    for item in plan.adapters:
        stop, line = item.params.get("stop"), item.params.get("line")
        if (
            item.name == "transit_bvg"
            and isinstance(stop, str)
            and 0 < len(stop.strip()) <= MAX_STOP_QUERY_CHARS
            and stop.strip().lower() in worry_text.lower()
        ):
            queries.append((stop.strip(), line.strip() if isinstance(line, str) else None))
    return queries


def _pin_stops(
    plan: Plan, code: str, worry_text: str, stop_ids: dict[tuple[str, str | None], str]
) -> str:
    """Turn transit_bvg's `stop` name into the looked-up id, in the plan and in run.py."""
    for item in plan.adapters:
        if item.name != "transit_bvg":
            continue
        params = item.params
        if "stop_id" in params:
            # Only an id the person wrote themselves; never one from the model's memory.
            if set(params) != {"stop_id"} or str(params["stop_id"]).strip() not in worry_text:
                raise MissingInput("transit_bvg")
            continue
        stop, line = params.get("stop"), params.get("line")
        if set(params) - {"stop", "line"} or not isinstance(stop, str) or not stop.strip():
            raise CodegenError('transit_bvg takes params {"stop": "<name>", "line": "<line>"}')
        if stop.strip().lower() not in worry_text.lower():
            raise MissingInput("transit_bvg")  # a stop the person didn't name
        key = (stop.strip(), line.strip() if isinstance(line, str) else None)
        if key not in stop_ids:
            raise MissingInput("transit_bvg")  # the lookup found no such stop (for that line)
        if not re.search(rf"[\"']{STOP_PLACEHOLDER}[\"']", code):
            raise CodegenError(f'run.py must set STOP_ID = "{STOP_PLACEHOLDER}" exactly')
        code = re.sub(rf"([\"']){STOP_PLACEHOLDER}([\"'])", rf"\g<1>{stop_ids[key]}\g<2>", code)
        item.params = {"stop_id": stop_ids[key]}
    return code


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


def build(
    content: str, worry_text: str, stop_ids: dict[tuple[str, str | None], str] | None = None
) -> Generated:
    """Raises MissingInput (park and ask) or CodegenError (feed back and retry).

    `stop_ids` holds the Warden's lookups for `stop_queries(content)`; a query missing from it
    means no such stop was found."""
    plan, code = parse_answer(content)
    code = _pin_stops(plan, code, worry_text, stop_ids or {})
    _check_inputs_given(plan, worry_text)
    adapters = resolve(plan)
    _check_transit_defaults(plan, code, worry_text)
    interval = min(max(plan.interval_s, MIN_INTERVAL_S), MAX_INTERVAL_S)
    return Generated(adapters=adapters, code=code, interval_s=interval)


def first_messages(text: str, t: Triage, now: datetime) -> list[Message]:
    deadline = t.deadline.isoformat() if t.deadline else "none"
    return [
        Message("system", SYSTEM),
        Message(
            "user",
            f"Current time: {now.astimezone(UTC).isoformat()} "
            f"(Europe/Berlin: {now.astimezone(LOCAL_TZ).isoformat()})\n"
            "The deadline below is UTC; the person's times are Europe/Berlin local.\n"
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
