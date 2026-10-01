from typing import Any, Literal

from pydantic import AwareDatetime, BaseModel, Field

# Mirrors docs/CONTRACTS.md. Keep in sync with app/src/api/schemas.ts.

WorryType = Literal[
    "unclassified", "checkable", "deadline", "person", "social", "uncontrollable"
]  # "unclassified" is T-07's addition: the pre-triage placeholder POST /api/worries sets
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


# --- T-07 additions below: request bodies, reassurance/people, sharing rules, ledger, events ---

ReassuranceQuestion = Literal["ok", "home"]
ReassuranceLevel = Literal["normal", "unusual", "help", "unknown"]
ReassuranceReason = Literal[
    "active_as_usual",
    "quieter_than_usual",
    "do_not_disturb",
    "asked_for_help",
    "not_enough_data",
    "arrived",
    "not_arrived",
]
EventType = Literal[
    "worry.updated", "watcher.result", "approval.needed", "alert.act_now", "peer.answer"
]


class WorryCreateRequest(BaseModel):
    text: str


class OutcomeRequest(BaseModel):
    fear_came_true: bool


class Peer(BaseModel):
    id: str = Field(pattern=r"^p_[0-9A-HJKMNP-TV-Z]{26}$")
    display_name: str
    public_key: str
    paired_at: AwareDatetime
    # Same 8 digits on both devices, from both public keys; compared by the humans after
    # pairing (T-17 gap, THREAT_MODEL A7). Computed on read, never stored or sent.
    fingerprint: str = Field(pattern=r"^[0-9]{4} [0-9]{4}$")


class ReassuranceAnswer(BaseModel):
    level: ReassuranceLevel
    reason: ReassuranceReason
    ts: AwareDatetime


class PrivacyReceipt(BaseModel):
    bytes_sent: int
    fields_shared: list[str]
    location_shared: bool
    egress_log_ref: str


class PeopleListItem(BaseModel):
    peer: Peer
    last_answer: ReassuranceAnswer | None
    last_answer_at: AwareDatetime | None
    # When I last asked, answered or not: the 10-minute cooldown runs from here.
    last_asked_at: AwareDatetime | None


class AskPeerRequest(BaseModel):
    q: ReassuranceQuestion


class AskPeerResponse(BaseModel):
    answer: ReassuranceAnswer
    receipt: PrivacyReceipt


class SharingRule(BaseModel):
    peer_id: str = Field(pattern=r"^p_[0-9A-HJKMNP-TV-Z]{26}$")
    allowed_questions: list[ReassuranceQuestion]
    allowed_levels: list[ReassuranceLevel]
    active: bool


class QuestionLogEntry(BaseModel):
    id: str
    peer_id: str = Field(pattern=r"^p_[0-9A-HJKMNP-TV-Z]{26}$")
    question: ReassuranceQuestion
    asked_at: AwareDatetime
    answer_level: ReassuranceLevel


class SharingRulesResponse(BaseModel):
    rules: list[SharingRule]
    questions_log: list[QuestionLogEntry]


# --- T-14/T-15 additions: pairing (CONTRACTS §2/§3). Zod mirrors land with the app in T-17. ---


class PairingStartRequest(BaseModel):
    display_name: str = Field(min_length=1, max_length=64)  # what *I* call the peer; local only


class PairingStartResponse(BaseModel):
    pairing_id: str = Field(pattern=r"^pr_[0-9A-HJKMNP-TV-Z]{26}$")
    code: str = Field(pattern=r"^[0-9A-HJKMNP-TV-Z]{8}$")
    expires_at: AwareDatetime


class PairingStatusResponse(BaseModel):
    """`GET /api/pairing/{pairing_id}`: the code-showing side waits on this."""

    state: Literal["waiting", "paired", "expired"]
    peer: Peer | None


class PairingJoinRequest(BaseModel):
    code: str = Field(min_length=8, max_length=16)  # normalised server-side (case, dashes)
    display_name: str = Field(min_length=1, max_length=64)


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class PushSubscription(BaseModel):
    endpoint: str
    keys: PushKeys


class LedgerResponse(BaseModel):
    worries_total: int
    active: int
    never_needed_you: int
    needed_you: int
    median_warning_lead_h: float
    came_true_rate: float
    came_true_by_type: dict[str, float]
    watchers_built: int
    sandboxes_live: int
    endpoints_denied: int
    peer_questions_answered: int
    locations_shared: Literal[0] = 0


class Event(BaseModel):
    type: EventType
    data: dict[str, Any]
