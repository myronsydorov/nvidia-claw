from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field

# Mirrors docs/CONTRACTS.md. Keep in sync with app/src/api/schemas.ts.

WorryType = Literal["checkable", "deadline", "person", "social", "uncontrollable"]
WorryStatus = Literal[
    "triaging",
    "compiling",
    "awaiting_approval",
    "watching",
    "needs_you",
    "resolved",
    "parked",
    "failed",
]
WatcherState = Literal[
    "draft", "dry_run_failed", "awaiting_approval", "active", "paused", "retired"
]
TimelineKind = Literal[
    "created",
    "triaged",
    "compiled",
    "approval_requested",
    "approved",
    "denied",
    "checked",
    "act_now",
    "resolved",
    "let_go",
    "parked",
    "failed",
]


class HealthResponse(BaseModel):
    status: Literal["ok"]
    sandboxes_live: int


class Worry(BaseModel):
    id: str = Field(pattern=r"^w_[0-9A-HJKMNP-TV-Z]{26}$")
    text: str
    type: WorryType
    fear: str
    deadline: AwareDatetime | None
    status: WorryStatus
    watcher_id: str | None = Field(pattern=r"^wt_[0-9A-HJKMNP-TV-Z]{26}$")
    resolution: str | None
    fear_came_true: bool | None
    created_at: AwareDatetime
    updated_at: AwareDatetime


class PermissionLine(BaseModel):
    method: Literal["GET"]
    host: str
    path: str
    why: str


class Evidence(BaseModel):
    source: str
    checked_at: AwareDatetime
    data: dict[str, Any]


class WatchResult(BaseModel):
    status: Literal["ok", "act_now", "resolved", "error"]
    summary: str = Field(max_length=140)
    evidence: Evidence
    fear_came_true: bool | None
    next_check_s: int


class Watcher(BaseModel):
    id: str = Field(pattern=r"^wt_[0-9A-HJKMNP-TV-Z]{26}$")
    worry_id: str = Field(pattern=r"^w_[0-9A-HJKMNP-TV-Z]{26}$")
    adapters: list[str]
    code: str
    policy_yaml: str
    policy_summary: list[PermissionLine]
    sandbox_name: str = Field(pattern=r"^cw-[a-z0-9-]{1,16}$")
    interval_s: int = Field(ge=300, le=86400)
    state: WatcherState
    last_result: WatchResult | None


class TimelineEvent(BaseModel):
    at: AwareDatetime
    kind: TimelineKind
    text: str = Field(max_length=140)


class WorrySummary(BaseModel):
    worry: Worry
    last_result: WatchResult | None


class WorryDetail(BaseModel):
    worry: Worry
    watcher: Watcher | None
    timeline: list[TimelineEvent]
