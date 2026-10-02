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
| `deadline` | datetime? | after this, the worry resolves automatically. Stored UTC; the person's times are Europe/Berlin local, and the app shows them that way |
| `status` | enum `triaging \| compiling \| awaiting_approval \| watching \| needs_you \| resolved \| parked \| failed` | `parked`: it can't be watched by nature (social, uncontrollable, about a person) or needs something from the person (a link, a stop); `failed`: building its watcher failed. `resolution` then says which phase failed in one sentence, nothing was set up (no watcher, no sandbox), `POST …/retry` builds again, and it isn't counted in the ledger |
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
| `kind` | enum `created \| triaged \| compiled \| approval_requested \| approved \| denied \| checked \| act_now \| resolved \| let_go \| retried \| parked \| failed \| test` | `test`: appended by `scripts/mark_test_worry.py` to a worry created to test the system; it is then not counted in the ledger |
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
string at declare-time. Paths are written in **OpenShell's canonical form** (ADR-0001, T-04): escapes of
path-legal characters decoded (`%40`→`@`), every other escape kept as upper-case `%XX` (`%23`, `%20`),
no `*`, `;`, `%2F`, control bytes, dot or empty segments; `parse_https_url` canonicalizes a
worry-supplied URL (`adapters.base.canonical_path`). `Endpoint.why` becomes `PermissionLine.why` on the generated policy card,
so it is declared once per endpoint, not threaded through separately. Adapters with a provider host
fixed at build time (`parcel_dhl`, `weather_openmeteo`, `flight_status`) expose a static
`ADAPTER: Adapter` constant; adapters whose host and/or path a worry supplies at compile time
(`transit_bvg`'s stop ID; `web_diff`, `http_json`, `rss`, `ics_calendar`'s target URL) expose a
`declare(...) -> Adapter` factory instead.

v1 adapters: `http_json`, `rss`, `web_diff`, `imap_search`, `ics_calendar`, `weather_openmeteo`, `transit_bvg`, `parcel_dhl`, `flight_status`. `imap_search` is not yet built — IMAP isn't an HTTP GET call, and `Endpoint.method: Literal["GET"]` mirrors `PermissionLine.method`, so adding it needs a new method/protocol literal plus an ADR (AGENTS.md invariant #2: "GET-only unless an ADR says otherwise").

## 2. Reassurance (Layer 2)

### Pairing
A one-time 8-character code (Crockford base32, 10-minute expiry) on device A is typed on device B. The devices swap X25519 public keys through the relay. Stored as `Peer{ id: p_<ulid>, display_name, public_key, paired_at }`. The API adds `fingerprint: "dddd dddd"`: 8 digits from BLAKE2b over both public keys (sorted) plus the joiner's fresh 16-byte `nonce` from the sealed `pair_accept`, so both devices show the same number and a key can't be ground offline to match it. It is computed on read, never stored or sent over the relay. The two people compare it after pairing: someone who saw the code and joined first would show a different number on the offerer's screen, and either side can then `DELETE /api/people/{id}`. Display names are local: each side names the other, and no name crosses the relay.
1. A: `POST /api/pairing {display_name}` → `{code, expires_at}`. A derives `(mailbox_id, key) = Argon2id(code)` and posts a SecretBox'd `{ "t": "pair_offer", "public_key", "expires_at" }` to `mailbox_id`. A stores the derived key, never the code.
2. B: `POST /api/pairing/join {code, display_name}` → `Peer`. B opens the offer, saves A, and posts a sealed box `{ "t": "pair_accept", "public_key", "proof", "nonce" }` to A's mailbox, where `proof` = keyed BLAKE2b(key, A_pk ‖ B_pk). B refuses (`409`) a code from a Warden it is already paired with: re-pairing starts with `DELETE /api/people/{id}`.
3. A's mailbox poller checks the proof against its live pairings, saves B, and deletes the pairing, so the code works once.

A new peer gets a default SharingRule on both sides: `{ allowed_questions: ["ok"], allowed_levels: all four, active: false }`. It becomes active only when the owner confirms the fingerprints match (`POST /api/people/{id}/confirm`). Until then, any question about them gets `unknown / not_enough_data`.

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
- `PairingStartRequest { display_name: str(1..64) }` → `PairingStartResponse { pairing_id: pr_<ulid>, code: str(8, Crockford), expires_at: datetime }`
- `PairingStatusResponse { state: "waiting" | "paired" | "expired", peer: Peer | null }` (`GET /api/pairing/{pairing_id}`; a completed pairing stays readable for an hour after its code expires, and an unknown id reads as `expired`)
- `PairingJoinRequest { code: str (case and dashes ignored), display_name: str(1..64) }` → `Peer`

### PeopleListItem (items of `GET /api/people`)
`{ "peer": Peer, "last_answer": ReassuranceAnswer | null, "last_answer_at": datetime | null, "last_asked_at": datetime | null }`. `last_asked_at` is when I last asked, answered or not; the 10-minute cooldown runs from it.

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
| POST | `/api/worries/{id}/retry` | a `failed` build → `triaging` again (`retried` event); `409` for any other status; returns WorryDetail |
| POST | `/api/worries/{id}/let-go` | user closes it → `resolved`; returns WorryDetail |
| POST | `/api/worries/{id}/outcome` | `{ fear_came_true: bool }` → returns WorryDetail |
| GET | `/api/people` | list[PeopleListItem] — peers + last answer |
| POST | `/api/people/{peer_id}/ask` | `{ q }` → AskPeerResponse (ReassuranceAnswer + PrivacyReceipt); `404` unknown peer, `503` no relay / relay down, `504` no answer in time (never a made-up answer), `502` the peer's answer failed our vocabulary check, `429` asked this person less than 10 minutes ago, counted from when the question was sent, answered or not (`WARDEN_ASK_COOLDOWN_S`; no "check again" loop, AGENTS #9) |
| POST | `/api/people/{peer_id}/confirm` | the fingerprints matched: my SharingRule for them becomes active → `204`; `404` unknown peer |
| DELETE | `/api/people/{peer_id}` | un-pair: forgets the peer and their SharingRule (the question log stays) → `204`; `404` unknown peer |
| GET | `/api/pairing/{pairing_id}` | PairingStatusResponse: the code-showing side waits on this |
| POST | `/api/pairing` | PairingStartRequest → PairingStartResponse; `503` without a relay |
| POST | `/api/pairing/join` | PairingJoinRequest → Peer; `422` malformed code, `404` no live pairing, `409` own code or already paired, `503` without a relay |
| POST | `/api/me/check-in` | "I'm OK" → `204`; clears "I need help" |
| POST/DELETE | `/api/me/help` | set / clear "I need help" → `204` |
| GET | `/api/me/signal` | ReassuranceAnswer: what an allowed peer asking "ok?" would get right now |
| GET/PUT | `/api/sharing-rules` | SharingRulesResponse — what others may ask about me; plus the log of questions |
| GET | `/api/ledger` | LedgerResponse — stats-wall aggregates |
| GET | `/api/events` | server-sent events: `worry.updated`, `watcher.result`, `approval.needed`, `alert.act_now`, `peer.answer` |
| POST | `/api/push/subscribe` | PushSubscription body → `204` |
| POST | `/api/talk` | TalkRequest `{ text }` (1–1000 chars) → TalkReply `{ reply, at }`: one turn with the brain (Warden → loopback OpenClaw `/v1/chat/completions` → brain → MCP tools). `422` text with a link or web address (it goes through `POST /api/worries`, THREAT_MODEL A12); `429` a turn less than 5 s ago, more than 20 in an hour, or one still running; `503` the brain can't be reached or didn't answer (nothing is claimed). `reply` is plain text, ≤ 2000 chars, control characters stripped; clients render it as escaped text |
| GET | `/api/daily-close` | DailyClose \| null: the latest note the brain wrote for Home |
| POST | `/api/daily-close` | the brain writes today's close now → DailyClose; `429` one was written less than 10 min ago; `503` brain unreachable; `502` the brain's note named a number its tools didn't confirm (discarded, nothing stored) |
| GET | `/api/health` | liveness + sandbox count — `{ "status": "ok", "sandboxes_live": 0 }` |

All `/api/*` routes, including `/api/health`, require the bearer device token; a missing or wrong token is `401`.

## 4. MCP tools (Warden → brain)
`custody.hand_over(text)`, `custody.list(status?)`, `custody.get(id)`, `custody.let_go(id)`, `custody.record_outcome(id, came_true)`, `custody.ask_peer(peer_id, q)`, `custody.ledger()`, `custody.today()`.

`today()` → DayNumbers `{ date, checks_run, alerts_sent, needed_you, watching: [{ id, text }] }`: for today (local day, `WARDEN_TZ`, default Europe/Berlin), from stored check results and timeline events, test worries excluded. `needed_you` = worries with an `act_now` or `failed` event today. The daily close (below) uses it.
The brain **cannot** approve policies. Approval only ever comes from the human, in the app.

**Transport (T-11):** an MCP server named `custody`, mounted on the Warden at **`/mcp/`** (Streamable
HTTP, stateless, JSON responses), with tools `hand_over`, `list`, `get`, `let_go`,
`record_outcome`, `ask_peer`, `ledger`, `today` (the dotted names above are `server.tool`). Auth: bearer
`WARDEN_MCP_TOKEN`, which must differ from the device token (`/mcp/` answers `401` without it).
Host headers outside loopback and `WARDEN_MCP_ALLOWED_HOSTS` get `421`. Each tool dispatches
in-process to the matching `/api` route, and ids must match `w_<ulid>` / `p_<ulid>` exactly.
Output: Worry fields plus the watcher's `adapters`, `permissions` (PermissionLine list), `state`,
`interval_s` and `last_result`. `last_result` passes through `guard.guard_watch_result`
(`evidence.data` dropped). Timeline texts and `resolution` are wrapped as `<untrusted_data>`.
Watcher `code` and `policy_yaml` are never returned.

## 5. Ledger (`GET /api/ledger`)
`{ worries_total, active, never_needed_you, needed_you, median_warning_lead_h, came_true_rate, came_true_by_type{}, watchers_built, sandboxes_live, endpoints_denied, peer_questions_answered, locations_shared: 0, checks_run, alerts_sent, checks_since }` (`peer_questions_answered` = entries in my question log)

- `checks_run`: watcher runs whose result the scheduler stored (one row per run in the Warden's check log, any status), test worries excluded. `checks_since`: datetime of the first stored check, or `null` when none; the check log started on 2026-10-02, so earlier runs aren't counted (the app says "since …"). `alerts_sent`: `act_now` timeline events of counted worries (each one is an interruption).

- **Build failures are not counted** in any total: a worry with a `failed` event that was never `approved` (a watcher paused after errors was approved, so it counts). `watchers_built` counts watchers that passed their dry run.
- **Test worries are not counted** either: a worry with a `test` timeline event, and its watcher (not in `watchers_built`). Test peers are removed with `DELETE /api/people/{id}`, and a question log entry only exists for questions asked about me.
- `median_warning_lead_h`, `came_true_by_type` and `endpoints_denied` are **not measured yet** (always `0.0`, `{}`, `0`); the app labels them so and claims nothing from them.

- `came_true_rate`: a fraction from 0 to 1 = `needed_you / (needed_you + never_needed_you)`, i.e. of the closed worries with a known outcome, the share whose fear came true. It is `0.0` while no outcome is known; clients must then check `needed_you + never_needed_you = 0` and claim nothing (the app shows "No outcomes yet"). `came_true_by_type` uses the same unit per worry type.
- DESIGN §6 also mentions "rules approved" and "bytes that left the friend's device". They are **deliberately not** in this response: the per-answer privacy receipt already shows the bytes, and approvals are visible per worry.

## 6. Daily close (T-brain, 2 Oct)
`DailyClose { date: "YYYY-MM-DD", text: str (≤ 400), written_at: datetime, checks_run: int, alerts_sent: int, needed_you: int }`.
Once a day after `WARDEN_DAILY_CLOSE_AT` (default `21:00`, `WARDEN_TZ`), and on `POST /api/daily-close`, the Warden asks the brain over the loopback chat endpoint to call `custody.today()` and write 2–3 plain sentences: what it watched, how many checks ran, what needed the person. **The Warden accepts the note only if every number in it is one `today()` confirms** (or a digit of the date or a watched worry's own text); otherwise it asks once more, then stores nothing. The numbers fields are the Warden's own count at writing time. One note per date (a later one replaces it).
