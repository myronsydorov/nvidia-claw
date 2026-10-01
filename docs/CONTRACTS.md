# Contracts: the source of truth

Change this file **first**, then the Pydantic models (`warden/src/warden/models.py`), the zod schemas (`app/src/api/schemas.ts`), and then the code. IDs are prefixed ULIDs. Times are ISO 8601 UTC.

## 1. Core entities

### Worry
| field | type | notes |
|---|---|---|
| `id` | `w_<ulid>` | |
| `text` | str | as the user wrote or said it |
| `type` | enum `unclassified \| checkable \| deadline \| person \| social \| uncontrollable` | `unclassified` from creation until triage sets a real value |
| `fear` | str | the precise bad outcome, e.g. "parcel not delivered by 2026-10-02T16:00Z"; `""` until triage runs |
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

### TimelineEvent
| field | type | notes |
|---|---|---|
| `at` | datetime | |
| `kind` | enum `created \| triaged \| compiled \| approval_requested \| approved \| denied \| checked \| act_now \| resolved \| let_go \| parked \| failed` | |
| `text` | str | ≤ 140 chars, plain language, shown as-is in the app |

### WorrySummary (items of `GET /api/worries`)
`{ "worry": Worry, "last_result": WatchResult | null }`

### WorryDetail (`GET /api/worries/{id}`)
`{ "worry": Worry, "watcher": Watcher | null, "timeline": [TimelineEvent] }` (timeline oldest first)

### AdapterDeclaration (`warden/src/warden/adapters/*.py`)
```python
Adapter(
  name="parcel_dhl",
  endpoints=[Endpoint(host="api-eu.dhl.com", port=443, method="GET", path="/track/shipments",
                       why="check parcel status")],
  secrets=["DHL_API_KEY"],        # injected by the OpenShell provider, never written into code
  description="Track a DHL shipment by tracking number")
```
Every `Endpoint.path` is an exact literal path, never a prefix or wildcard — a dynamic identifier
(a tracking number, a stop ID) belongs in the query string, or gets baked into one exact path
string at declare-time. `Endpoint.why` becomes `PermissionLine.why` on the generated policy card,
so it is declared once per endpoint, not threaded through separately. Adapters with a provider host
fixed at build time (`parcel_dhl`, `weather_openmeteo`, `flight_status`) expose a static
`ADAPTER: Adapter` constant; adapters whose host and/or path a worry supplies at compile time
(`transit_bvg`'s stop ID; `web_diff`, `http_json`, `rss`, `ics_calendar`'s target URL) expose a
`declare(...) -> Adapter` factory instead.

v1 adapters: `http_json`, `rss`, `web_diff`, `imap_search`, `ics_calendar`, `weather_openmeteo`, `transit_bvg`, `parcel_dhl`, `flight_status`. `imap_search` is not yet built — IMAP isn't an HTTP GET call, and `Endpoint.method: Literal["GET"]` mirrors `PermissionLine.method`, so adding it needs a new method/protocol literal plus an ADR (AGENTS.md invariant #2: "GET-only unless an ADR says otherwise").

## 2. Reassurance (Layer 2)

### Pairing
A one-time 8-character code (Crockford base32, 10-minute expiry) on device A is typed on device B. The devices swap X25519 public keys through the relay. Stored as `Peer{ id: p_<ulid>, display_name, public_key, paired_at }`. Display names are local: each side names the other, and no name crosses the relay.
1. A: `POST /api/pairing {display_name}` → `{code, expires_at}`. A derives `(mailbox_id, key) = Argon2id(code)` and posts a SecretBox'd `{ "t": "pair_offer", "public_key", "expires_at" }` to `mailbox_id`. A stores the derived key, never the code.
2. B: `POST /api/pairing/join {code, display_name}` → `Peer`. B opens the offer, saves A, and posts a sealed box `{ "t": "pair_accept", "public_key", "proof" }` to A's mailbox, where `proof` = keyed BLAKE2b(key, A_pk ‖ B_pk).
3. A's mailbox poller checks the proof against its live pairings, saves B, and deletes the pairing, so the code works once.

A new peer gets a default SharingRule on both sides: `{ allowed_questions: ["ok"], allowed_levels: all four, active: true }`.

Key ids (mailbox addresses) are BLAKE2b-128 hex of the public key. Messages between paired peers are authenticated `crypto_box` (X25519 + XSalsa20-Poly1305; see the ADR-0004 amendment); every plaintext envelope rejects unknown fields.

### SharingRule (owned by the person being asked about)
`{ peer_id, allowed_questions: ["ok", "home"], allowed_levels: ["normal","unusual","help","unknown"], active: true }`

### ReassuranceQuery (encrypted to the peer)
`{ "t": "query", "q": "ok | home", "nonce": "<32 hex>", "ts": "…" }`. There is no `from`: peer ids are local to each Warden, so the sender is identified by the authenticated box and `sender_key_id`. A query from an unpaired key, one that fails authentication, one older than 5 minutes, or a replayed nonce is dropped, and so is anything over 30 queries per peer per hour. Every other query is written to the owner's question log.

### ReassuranceAnswer (encrypted back), fixed vocabulary only
```json
{ "level": "normal | unusual | help | unknown",
  "reason": "active_as_usual | quieter_than_usual | do_not_disturb | asked_for_help | not_enough_data | arrived | not_arrived",
  "ts": "…" }
```
Any field or value outside this vocabulary gets **rejected by the sender's own Warden before encryption**: nothing is sent, and the log records `unknown`. It travels as `{ "t": "answer", "re": "<the query's nonce>", "answer": ReassuranceAnswer }`, and the asker re-validates it with the same strict model. The owner's SharingRule turns anything it doesn't allow (inactive, question or level not allowed) into `unknown / not_enough_data`. In v1, `home` always answers `unknown / not_enough_data`: there is no arrival signal without location.

### "Normal day" signal (v1, computed locally)
Inputs: computer activity (OS idle time) against hours learned over 14 days, a local .ics calendar's busy/free, the last check-in, and an explicit "I need help". Precedence: help → `help/asked_for_help`; check-in < 3 h → `normal/active_as_usual`; busy → `normal/do_not_disturb`; < 3 days of history → `unknown/not_enough_data`; active < 30 min → `normal/active_as_usual`; usually-active hour and idle ≥ 2 h → `unusual/quieter_than_usual`; otherwise `normal/active_as_usual`.

### PrivacyReceipt (shown in the app)
`{ "bytes_sent": 212, "fields_shared": ["level","reason","ts"], "location_shared": false, "egress_log_ref": "relay:<message id>" }`. `bytes_sent` is the exact size of the answer's POST body to the relay (canonical JSON `{"ciphertext","sender_key_id"}`).

### Pairing and "me" shapes (T-14/T-15; zod mirrors land with the app in T-17)
- `PairingStartRequest { display_name: str(1..64) }` → `PairingStartResponse { code: str(8, Crockford), expires_at: datetime }`
- `PairingJoinRequest { code: str (case and dashes ignored), display_name: str(1..64) }` → `Peer`

### PeopleListItem (items of `GET /api/people`)
`{ "peer": Peer, "last_answer": ReassuranceAnswer | null, "last_answer_at": datetime | null }`

### AskPeerResponse (`POST /api/people/{peer_id}/ask`)
`{ "answer": ReassuranceAnswer, "receipt": PrivacyReceipt }`

### QuestionLogEntry (an entry in `SharingRulesResponse.questions_log`)
`{ "id": str, "peer_id": "p_<ulid>", "question": "ok | home", "asked_at": datetime, "answer_level": "normal | unusual | help | unknown" }`

### SharingRulesResponse (`GET/PUT /api/sharing-rules`)
`{ "rules": [SharingRule], "questions_log": [QuestionLogEntry] }` (questions_log newest first). `PUT` takes and returns the same shape and replaces the full `rules` list; `questions_log` is read-only (server-maintained).

### PushSubscription (body of `POST /api/push/subscribe`)
`{ "endpoint": str, "keys": { "p256dh": str, "auth": str } }`

### Relay API (ciphertext only)
- `POST /v1/mailbox/{recipient_key_id}` with body `{ ciphertext, sender_key_id }` → `202 { id }`
- `GET /v1/mailbox/{my_key_id}?since=<id>` → `[ { id, ciphertext, sender_key_id, ts } ]` (ids are increasing integers; `since` is exclusive)
- `GET /v1/health` → `{ "status": "ok" }`

Key ids are 32 lowercase hex chars. The ciphertext is standard base64, at most 4 KiB decoded (larger → `413`), and unknown body fields → `422`. The relay stores the ciphertext as bytes, keeps a message for 24 h, and keeps at most 200 per mailbox and 50k in total (`507` when full). A POST needs a `Content-Length` of at most 16 KiB (`411` / `413`). There is no mailbox auth (THREAT_MODEL A6).

## 3. Warden app API (`/api`, bearer device token)
| method | path | purpose |
|---|---|---|
| POST | `/api/worries` | `{ text }` → Worry (status `triaging`) |
| GET | `/api/worries` | list[WorrySummary], with filters `status=` |
| GET | `/api/worries/{id}` | WorryDetail (Worry + Watcher + timeline) |
| POST | `/api/worries/{id}/approve` | approve the watcher's policy → `active`; returns WorryDetail |
| POST | `/api/worries/{id}/deny` | → `parked`; returns WorryDetail |
| POST | `/api/worries/{id}/let-go` | user closes it → `resolved`; returns WorryDetail |
| POST | `/api/worries/{id}/outcome` | `{ fear_came_true: bool }` → returns WorryDetail |
| GET | `/api/people` | list[PeopleListItem] — peers + last answer |
| POST | `/api/people/{peer_id}/ask` | `{ q }` → AskPeerResponse (ReassuranceAnswer + PrivacyReceipt); `404` unknown peer, `503` no relay / relay down, `504` no answer in time (never a made-up answer), `502` the peer's answer failed our vocabulary check |
| POST | `/api/pairing` | PairingStartRequest → PairingStartResponse; `503` without a relay |
| POST | `/api/pairing/join` | PairingJoinRequest → Peer; `422` malformed code, `404` no live pairing, `409` own code, `503` without a relay |
| POST | `/api/me/check-in` | "I'm OK" → `204`; clears "I need help" |
| POST/DELETE | `/api/me/help` | set / clear "I need help" → `204` |
| GET | `/api/me/signal` | ReassuranceAnswer: what an allowed peer asking "ok?" would get right now |
| GET/PUT | `/api/sharing-rules` | SharingRulesResponse — what others may ask about me; plus the log of questions |
| GET | `/api/ledger` | LedgerResponse — stats-wall aggregates |
| GET | `/api/events` | server-sent events: `worry.updated`, `watcher.result`, `approval.needed`, `alert.act_now`, `peer.answer` |
| POST | `/api/push/subscribe` | PushSubscription body → `204` |
| GET | `/api/health` | liveness + sandbox count — `{ "status": "ok", "sandboxes_live": 0 }` |

All `/api/*` routes, including `/api/health`, require the bearer device token; a missing or wrong token is `401`.

## 4. MCP tools (Warden → brain)
`custody.hand_over(text)`, `custody.list(status?)`, `custody.get(id)`, `custody.let_go(id)`, `custody.record_outcome(id, came_true)`, `custody.ask_peer(peer_id, q)`, `custody.ledger()`.
The brain **cannot** approve policies. Approval only ever comes from the human, in the app.

## 5. Ledger (`GET /api/ledger`)
`{ worries_total, active, never_needed_you, needed_you, median_warning_lead_h, came_true_rate, came_true_by_type{}, watchers_built, sandboxes_live, endpoints_denied, peer_questions_answered, locations_shared: 0 }` (`peer_questions_answered` = entries in my question log)
