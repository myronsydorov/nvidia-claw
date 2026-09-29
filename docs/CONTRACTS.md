# Contracts: the source of truth

Change this file **first**, then the Pydantic models (`warden/src/warden/models.py`), the zod schemas (`app/src/api/schemas.ts`), and then the code. IDs are prefixed ULIDs. Times are ISO 8601 UTC.

## 1. Core entities

### Worry
| field | type | notes |
|---|---|---|
| `id` | `w_<ulid>` | |
| `text` | str | as the user wrote or said it |
| `type` | enum `checkable \| deadline \| person \| social \| uncontrollable` | set by triage |
| `fear` | str | the precise bad outcome, e.g. "parcel not delivered by 2026-10-02T16:00Z" |
| `deadline` | datetime? | after this, the worry resolves automatically |
| `status` | enum `triaging \| compiling \| awaiting_approval \| watching \| needs_you \| resolved \| parked \| failed` | |
| `watcher_id` | `wt_<ulid>`? | |
| `resolution` | str? | human-readable |
| `fear_came_true` | bool? | asked once when the worry closes |
| `created_at`, `updated_at` | datetime | |

### Watcher
| field | type | notes |
|---|---|---|
| `id` | `wt_<ulid>` | |
| `worry_id` | `w_<ulid>` | |
| `adapters` | list[str] | names from the adapter library |
| `code` | str | the generated `run.py` |
| `policy_yaml` | str | generated from the adapter declarations only |
| `policy_summary` | list[PermissionLine] | shown on the permission card |
| `sandbox_name` | str | `cw-<short id>`, 1–19 characters, a–z, 0–9 and `-` |
| `interval_s` | int | 300–86400 |
| `state` | enum `draft \| dry_run_failed \| awaiting_approval \| active \| paused \| retired` | |
| `last_result` | WatchResult? | |

### PermissionLine
`{ "method": "GET", "host": "api-eu.dhl.com", "path": "/track/shipments", "why": "check parcel status" }`

### WatchResult (the watcher's `stdout`, exactly one JSON object)
```json
{ "status": "ok | act_now | resolved | error",
  "summary": "≤ 140 chars, plain language",
  "evidence": { "source": "DHL", "checked_at": "…", "data": {} },
  "fear_came_true": null,
  "next_check_s": 3600 }
```
Invalid JSON or a missing `status` is treated as `error`. Three `error`s in a row pause the watcher and notify the user once.

### AdapterDeclaration (`warden/src/warden/adapters/*.py`)
```python
Adapter(
  name="parcel_dhl",
  endpoints=[Endpoint(host="api-eu.dhl.com", port=443, method="GET", path="/track/shipments")],
  secrets=["DHL_API_KEY"],        # injected by the OpenShell provider, never written into code
  description="Track a DHL shipment by tracking number")
```
v1 adapters: `http_json`, `rss`, `web_diff`, `imap_search`, `ics_calendar`, `weather_openmeteo`, `transit_bvg`, `parcel_dhl`, `flight_status`.

## 2. Reassurance (Layer 2)

### Pairing
A one-time 8-character code on device A is typed on device B. The devices swap X25519 public keys through the relay. Stored as `Peer{ id: p_<ulid>, display_name, public_key, paired_at }`.

### SharingRule (owned by the person being asked about)
`{ peer_id, allowed_questions: ["ok", "home"], allowed_levels: ["normal","unusual","help","unknown"], active: true }`

### ReassuranceQuery (encrypted to the peer)
`{ "q": "ok | home", "from": "p_…", "nonce": "…", "ts": "…" }`

### ReassuranceAnswer (encrypted back), fixed vocabulary only
```json
{ "level": "normal | unusual | help | unknown",
  "reason": "active_as_usual | quieter_than_usual | do_not_disturb | asked_for_help | not_enough_data | arrived | not_arrived",
  "ts": "…" }
```
Any field or value outside this vocabulary gets **rejected by the sender's own Warden before encryption**.

### PrivacyReceipt (shown in the app)
`{ "bytes_sent": 212, "fields_shared": ["level","reason","ts"], "location_shared": false, "egress_log_ref": "…" }`

### Relay API (ciphertext only)
- `POST /v1/mailbox/{recipient_key_id}` with body `{ ciphertext, sender_key_id }` → `202`
- `GET /v1/mailbox/{my_key_id}?since=` → `[ { id, ciphertext, sender_key_id, ts } ]`

## 3. Warden app API (`/api`, bearer device token)
| method | path | purpose |
|---|---|---|
| POST | `/api/worries` | `{ text }` → Worry (status `triaging`) |
| GET | `/api/worries` | list with filters `status=` |
| GET | `/api/worries/{id}` | Worry + Watcher + timeline |
| POST | `/api/worries/{id}/approve` | approve the watcher's policy → `active` |
| POST | `/api/worries/{id}/deny` | → `parked` |
| POST | `/api/worries/{id}/let-go` | user closes it → `resolved` |
| POST | `/api/worries/{id}/outcome` | `{ fear_came_true: bool }` |
| GET | `/api/people` | peers + last answer |
| POST | `/api/people/{peer_id}/ask` | `{ q }` → ReassuranceAnswer + PrivacyReceipt |
| GET/PUT | `/api/sharing-rules` | what others may ask about me; plus the log of questions |
| GET | `/api/ledger` | stats-wall aggregates |
| GET | `/api/events` | server-sent events: `worry.updated`, `watcher.result`, `approval.needed`, `alert.act_now`, `peer.answer` |
| POST | `/api/push/subscribe` | web-push subscription |
| GET | `/api/health` | liveness + sandbox count — `{ "status": "ok", "sandboxes_live": 0 }` |

## 4. MCP tools (Warden → brain)
`custody.hand_over(text)`, `custody.list(status?)`, `custody.get(id)`, `custody.let_go(id)`, `custody.record_outcome(id, came_true)`, `custody.ask_peer(peer_id, q)`, `custody.ledger()`.
The brain **cannot** approve policies. Approval only ever comes from the human, in the app.

## 5. Ledger (`GET /api/ledger`)
`{ worries_total, active, never_needed_you, needed_you, median_warning_lead_h, came_true_rate, came_true_by_type{}, watchers_built, sandboxes_live, endpoints_denied, peer_questions_answered, locations_shared: 0 }`
