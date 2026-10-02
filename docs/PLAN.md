# Plan: task board

Owner: **You** = Myron (infrastructure, real usage, video) · **Claude** = code.
Status: `todo · doing · done · cut`. Every task has **acceptance criteria and a check you can run**. An agent works on exactly one task ID at a time.

## Tue 29 Sep: foundation
| ID | Owner | Task | Acceptance / verify | Status |
|---|---|---|---|---|
| T-01 | You | Launch NemoClaw on Brev; onboard the NVIDIA API key | `nemoclaw status` shows the sandbox `Ready` and a healthy inference probe | done (DO host, `custody-brain`; evidence in HANDOFF.md) |
| T-02 | You | Turn on OpenClaw's `/v1/chat/completions` endpoint, bound to loopback; create the token | `curl -s localhost:<port>/v1/chat/completions …` returns a completion; the port is not reachable from outside | done (`scripts/check-gateway.sh`, `brain/gateway.md`) |
| T-03 | Claude | Repo scaffold: structure from AGENTS.md, Makefile, uv, pnpm, ruff/mypy/biome, CI, `.gitignore`, `.env.example` | `make lint typecheck test` passes on the empty skeleton; CI passes | done* |
| T-04 | Claude + You | **SPIKE:** sandbox per watcher. Create from the `watcher_runtime` image → apply the generated policy → exec `run.py` → parse the JSON → delete | Timings recorded in ADR-0001; a request to a host outside the policy is **denied and visible in the logs** | done§§ |
| T-05 | Claude | App shell on mock data: Home, Hand-over (animated steps + permission card), Worry detail; PWA manifest; design tokens | `pnpm -C app build` passes; a 390×844 screenshot matches the design notes | done† |
| T-06 | You | Start a real worry log (plain notes) to feed in once L1 works | ≥ 5 real worries written down | todo |

† T-05: app shell runs on an in-memory mock API (`app/src/api/client.ts`); fixtures parse through the zod contract schemas. CONTRACTS.md gained `TimelineEvent`, `WorrySummary` and `WorryDetail` to pin down the `/api/worries` response shapes.

§§ T-04 sub-item: decide whether `Endpoint.path` accepts percent-encoding once we know whether OpenShell matches raw or decoded paths; **security-reviewer required.** (From T-09: Google Calendar ICS links contain `%23`/`%40`, and `^/[A-Za-z0-9_./-]*$` rejects them.)
**Done (2026-10-01), on the DigitalOcean host:**
- **Driver:** `warden/src/warden/sandbox/openshell.py` (`CUSTODY_SANDBOX=openshell`) creates the sandbox network-less, then `policy set --wait`, uploads `/w/run.py`, execs, and deletes. `denials()` reads OpenShell's OCSF log.
- **Policy:** `compiler/policy.py` now emits OpenShell's real schema.
- **Image:** `watcher_runtime/image/Dockerfile`, built with `make watcher-image`.
- **Live check:** `make spike` shows declared endpoints allowed, a percent-encoded Google ICS link allowed, and `example.com`, an undeclared path and `%2F` denied, with OCSF `DENIED` lines in `openshell logs`. Timings are in ADR-0001: create 1.1 s, policy 8–9 s, exec 0.1 s, 12 MiB idle.
- **Percent-encoding:** OpenShell matches a *canonicalized* path, so `Endpoint.path` must be in that canonical form (`adapters.base.canonical_path`; ADR-0001, CONTRACTS §1). T-09's `school_calendar` case now builds.
- **Security-reviewer pass:** no invariant violations. Every finding is fixed and tested; the list is in ADR-0001.
- **Tests:** 556 Python + 83 app.

\* T-03: `make lint typecheck test` verified locally (evidence in the PR). CI itself is unverified until the first push to GitHub triggers `.github/workflows/ci.yml`.

## Wed 30 Sep: L1 end to end
| ID | Owner | Task | Acceptance / verify | Status |
|---|---|---|---|---|
| T-07 | Claude | Warden core: FastAPI, SQLite, models per CONTRACTS, server-sent events, device-token auth, `/api/health` | pytest covers every route; contract tests compare Pydantic with the zod schemas | done‡ |
| T-08 | Claude | Adapter library v1 (see CONTRACTS §1), each with endpoint declarations and fixture tests | `uv run pytest warden/adapters` passes; the policy generator output snapshots contain no wildcards | done§ |
| T-09 | Claude | Compiler: triage → code generation against adapters → policy generation → dry run → retry ×2 → park | 10 labelled sample worries: ≥ 8 routed correctly; generated watchers pass their dry run | done†† |
| T-10 | Claude | Scheduler, act-now alerts, auto-resolve at deadline, the "did it happen?" question | Simulated clock test: silence while `ok`, exactly one alert on `act_now` | done‖ |
| T-11 | Claude | Brain: OpenClaw `custody` skill, standing orders, MCP tool wiring | From chat, "I'm worried X" leads to a Worry appearing in `/api/worries` | done§§§ |
| T-12 | Claude | App wiring for L1: hand-over, permission approval, live status, detail, let-go | Playwright smoke: hand over → approve → status becomes `watching` | done¶ |
| T-13 | You | **Dogfood:** hand over your real worries from the phone | ≥ 6 worry types have been through the full flow | todo |

‡ T-07: all 14 `/api` routes from CONTRACTS §3, aiosqlite persistence, an in-process SSE bus, global bearer auth (incl. `/api/health`, plus `/docs`/`/openapi.json`/`/redoc` disabled per the security-reviewer pass), and `sandboxes_live` computed from the DB. `warden/tests/test_contract_zod_sync.py` diffs every Pydantic/zod pair field-by-field via `z.toJSONSchema`. No compiler/adapters/scheduler (T-08–T-10) — routes that depend on them return honest minimal/zero placeholders, commented inline.

§ T-08: 8 of 9 v1 adapters built — `transit_bvg`, `parcel_dhl`, `weather_openmeteo`, `web_diff`, `http_json` (required) plus `rss`, `ics_calendar`, `flight_status` (stretch, time allowed). `imap_search` deferred: IMAP isn't an HTTP GET call and `Endpoint.method`/`PermissionLine.method` are `Literal["GET"]`, so it needs a new method/protocol literal plus an ADR per AGENTS invariant #2 — out of scope for a library task. `warden/src/warden/compiler/policy.py` generates the OpenShell policy YAML + `policy_summary` from adapter declarations (dedupes identical endpoints, raises on a conflicting `why`); `policies/examples/*.yaml` are the checked-in golden snapshots (95 tests in `warden/tests/adapters`, wildcard-freedom asserted structurally via `Endpoint`/`Adapter` regex constraints and a field validator rejecting bare IP-literal hosts, not just a substring check).

‖ T-10: `warden/src/warden/scheduler.py` with an injectable `Clock` and a `PushNotifier` stub (logs kind + worry id only; T-18 swaps in web push). `ok` → silent (live `watcher.result` SSE only); `act_now` → one alert while the worry is `needs_you`; `resolved` → close, delete the sandbox, ask "Did what you feared happen?" unless the result already says; 3 errors in a row → `paused` (the sandbox is kept for inspection and still counts in `sandboxes_live`) + one notification; deadline → auto-resolve. `next_check_s` is clamped to 300–86400 s. Scheduling state lives in an internal `schedule` table (not a contract). `WARDEN_SCHEDULER=off` disables the loop (the route tests set it). Security-reviewer fixes: a store-wide `write_lock` serialises the scheduler with approve/deny/let-go/outcome; a run claims its next slot *before* exec so no failure can cause 30 s re-runs; stdout is capped at 64 KiB, and `RecursionError`/`ValueError` count as `error`; `evidence` is bounded (source ≤ 64 chars, data ≤ 4 KiB, else `{truncated: true}`) before it is stored. **T-11 must:** pass `last_result` through `compiler/guard.py` (or drop `evidence.data`) before any MCP response reaches the brain. `warden/tests/test_scheduler.py`: 15 simulated-clock tests.

¶ T-12: `app/src/api/http.ts` is the real `/api` client: bearer device token (typed once on the Connect screen, kept in localStorage, never bundled) and every response zod-parsed. `/api/events` is read over `fetch`, not `EventSource`, because EventSource can't send the bearer header. It reconnects with exponential backoff, which resets only after a stream has stayed up ≥ 10 s, and emits a client-only `connected` signal so screens refetch. The mock API is kept behind `VITE_API_MODE=mock` (`pnpm dev:mock`). T-09 doesn't exist yet, so `warden/src/warden/compiler/mock.py` (`CUSTODY_COMPILER=mock`, refused unless `CUSTODY_SANDBOX=mock`) walks new worries to `awaiting_approval` with hand-written GET-only templates. **T-09 deletes it.** `make e2e` runs the Playwright smoke test (hand over → approve → `watching` → let go) against a real uvicorn Warden at 390×844. Merge note (2026-09-30): unified with T-10's `store.write_lock` (was a separate `app.state.worry_lock`) — the same one lock now serialises the scheduler, the mock compiler's check-then-save, and all four write routes (approve/deny/let-go/outcome). `test_let_go_racing_the_compile_save_wins` (mock compiler vs. let-go) and a new `test_scheduler_run_cannot_interleave_with_a_route` (scheduler vs. a write route) both fail if the lock is removed — verified by temporarily deleting it and re-running.

†† T-09: `warden/src/warden/compiler/` = `triage.py` (fast model → type/fear/deadline/route; the type decides the route) → `codegen.py` (code model → a ```json adapter plan + ```python run.py; resolved through the adapter registry; the permission-card `why` is ours, and `http_json` may not name secrets) → `gate.py` (AST gate: only `watcher_runtime.harness` + the declared adapters' `fetch`/`parse`; attribute access is an allowlist; no `match`/`class`, no `_`-prefixed identifier anywhere, no eval/exec/getattr/type/object/chr/print; `open()` only under /tmp/; URL literals must match declared endpoints; ≤ 8 KiB / 250 lines) → `policy.generate_policy` → `dryrun.py` (a throwaway `cwd-*` sandbox: create → policy → `write_file` run.py → exec → always delete; passes only on a valid, non-`error` WatchResult) → up to 2 retries, with the failure fed back through `guard.dry_run_feedback` (exit code, run.py line numbers, exception type, and a guarded message; stdout is never echoed) → otherwise `parked` with an honest `resolution` and the failed watcher kept as `dry_run_failed`. Person worries park with an L2 note and social/uncontrollable ones with "weekly worry time"; a model outage parks honestly. `guard.py` is the injection guard (nonce-tagged `<untrusted_data>`, control/bidi stripping, forged-tag removal); **T-11 should use `guard.guard_watch_result`** (drops `evidence.data`) for MCP responses. `llm.py`: NVIDIA Build over `httpx2`, `message.content` only, 429/5xx/transport retries with backoff and Retry-After, the key never logged (tested). `SandboxDriver.write_file` is new; approve now writes `/w/run.py`. `watcher_runtime/harness.py` gives watchers emit/fail/time/state helpers, so generated code needs no stdlib imports. **Security-reviewer pass:** the first gate could be bypassed (match class patterns, `gi_frame.f_builtins`, runtime-built `.format` strings, dunder defs). All are fixed via the attribute allowlist and identifier checks, with the payloads kept as regression tests. `harness.secret` was removed: `parcel_dhl` reads its own key, so generated code can't read or leak a secret. Other fixes: the checker feedback is guarded, a failed approve deletes its half-built sandbox, and worries left mid-compile by a restart are re-queued at startup. **For T-04:** don't attach secret providers to `cwd-*` dry-run sandboxes unless that's intended, because a DHL dry run needs the key. The scheduler's output parsing moved to `warden/watch_output.py`, shared with the dry run. **`compiler/mock.py` and `CUSTODY_COMPILER` are deleted.** Offline dev and e2e use `CUSTODY_LLM_REPLAY` (recorded answers, refused unless `CUSTODY_SANDBOX=mock`), and the real pipeline runs on them; route tests set `WARDEN_COMPILER=off`, like `WARDEN_SCHEDULER=off`. Tests: `warden/tests/compiler/` (gate 55, guard 8, llm 9, triage/codegen 19, pipeline 11) and `test_worry_compile_routes.py` (4, incl. the let-go-vs-compile-save race, which fails when the lock is removed — verified). The `fixtures/llm/replay.json` answers are **hand-written** in the live response shape and can be regenerated with `make eval-compiler ARGS=--record`. **Live eval 1 (2026-09-30): 5/10.** Every failure was a triage call that returned HTTP 200: `nemotron-3.5-lightning` wrote its reasoning into `content` and hit `max_tokens=1500` before the JSON (the recorded answers show it), and some passes had parsed a draft JSON from inside the reasoning. **Reliability fixes:** a `CallDiag` per attempt (outcome, HTTP status, finish_reason, latency, max_tokens, content/reasoning sizes; never the key), shown per failed case in the eval table (`--verbose` for all). Triage now sends `chat_template_kwargs: {"enable_thinking": false}` (documented for both models; dropped automatically on a 400), uses max_tokens 2500, and a `length` cut-off retries at once with double the limit (up to a cap). Timeouts are ≥ 120 s, with 4 attempts and jittered exponential backoff that honours Retry-After. The triage parser takes the last valid object after stripping `<think>`, and the re-ask no longer echoes the bad answer. If the fast model still fails, triage retries once with `CUSTODY_MODEL_CODE`. Eval cases run sequentially. **Live eval 2 (2026-10-01): 9/10 PASS**, and reasoning off is confirmed on the hosted endpoint (triage `reasoning=0c`, ~620 ms). The one failure, `school_calendar`, gave the model a real Google Calendar ICS link, which it used correctly, but `Endpoint.path` (`^/[A-Za-z0-9_./-]*$`) rejects its percent-encoding (`%23`, `%40`). Allowing that is deferred to T-04 (sub-item §§): decide once we know whether OpenShell matches raw or decoded paths, with a security-reviewer pass. Separately, if the worry lacks a URL or identifier (or the plan's URL isn't in the worry text, i.e. it was invented), the compiler no longer retries: it parks once with a fixed ask, e.g. "Send me the link to the calendar and I'll watch it." The recorded live answers (`warden/tests/fixtures/llm/recorded/`, checked for keys and auth headers) are replayed by `test_compiler_recorded_live.py`. **Honest limit, still true:** until T-04's OpenShell driver exists, the dry run's exec step is the mock sandbox, so generated watchers are gated and policy-checked but don't actually run until T-04 (running them on the host would break invariant #1).

§§§ T-11 (2026-10-01): the Warden serves the CONTRACTS §4 tools at `/mcp/` (`warden/mcp_server.py`, own `WARDEN_MCP_TOKEN`, no approval tool, output through `guard.py`; `test_mcp.py`). The `custody` skill and standing orders are installed in `custody-brain` (`scripts/install-brain.sh`). **Done 2026-10-02:** with Tailscale Serve on, plus one narrow ufw rule (brain container → tailnet IP:443, `scripts/ufw-brain-mcp.sh`), a chat through the gateway created worry `w_01M3WV2BR1ABGXMJ51ZGGMB5HG` in `/api/worries`. A standing order now forbids claiming a hand-over that no tool confirmed.

## Thu 1 Oct: L2, Ledger, push
| ID | Owner | Task | Acceptance / verify | Status |
|---|---|---|---|---|
| T-14 | Claude | Relay (ciphertext-only mailbox) plus pairing with a one-time code | Relay database dump contains no plain text (test); pairing works between two local Wardens | done‡‡ |
| T-15 | Claude | Reassurance: query/answer, vocabulary enforcement, sharing rules, "normal day" signal v1, privacy receipt | Answers outside the vocabulary are rejected (test); the receipt shows the bytes sent | done‡‡ |
| T-16 | You | Second install on the Intel MacBook (Ubuntu) as "Anna" | "Is Anna OK?" answered end to end between the two machines | doing: macOS now (not Ubuntu), `docs/ANNA_SETUP.md` + `scripts/anna-setup.sh` ready; proven between two Wardens on the host (HANDOFF block 5); the Mac run is yours |
| T-17 | Claude | App: People, sharing rules + question log, Ledger | Screenshots; Ledger numbers match `/api/ledger` | done¶¶ |
| T-18 | Claude | Web push (VAPID keys) for act-now alerts and approvals | A push arrives on the installed phone app | todo |
| T-19 | Claude | *Stretch, L3:* watcher bundle (code + policy + hash), publish/import, "Borrow a watcher" | An imported watcher runs with **exactly** its declared policy | todo |

‡‡ T-14 + T-15 (backend only; app/ untouched). **Relay** (`relay/src/relay/app.py`, `make relay`): a FastAPI + SQLite mailbox that stores ciphertext as BLOBs.
- Validation: key ids are 32 hex chars, the ciphertext is strict base64 ≤ 4 KiB (413), and unknown fields get a 422.
- Limits: Content-Length ≤ 16 KiB checked before the body is read, 24 h TTL, 200 per mailbox, 50k global (507).
- No mailbox auth (THREAT_MODEL A6).

**Warden** `warden/src/warden/reassurance/`:
- `keys` (X25519 identity in `WARDEN_KEY_PATH`, created 0600 and refused if group/other-readable).
- `crypto`: authenticated `Box` between peers (**ADR-0004 amendment**: a sealed box can't say who asks, so sharing rules couldn't be enforced), a sealed box for the pairing accept, and a SecretBox under Argon2id(code) for the offer.
- `vocabulary`: a strict `enforce` that runs before and after the sharing rule and always before encryption; the asker re-validates and answers 502 on junk.
- `messages`: strict envelopes.
- `signal` (v1 precedence in CONTRACTS §2) and `sources`: macOS `ioreg` / Linux `xprintidle` idle time sampled every 5 min, a local `.ics` file for busy/free, `CUSTODY_ACTIVITY=off`.
- `service`: pairing, ask, mailbox poller, question log, replay/staleness guard, 30 queries per peer per hour.

**New routes:** `POST /api/pairing`, `POST /api/pairing/join`, `POST /api/me/check-in`, `POST|DELETE /api/me/help`, `GET /api/me/signal`. Ask is now real: 404/503/504/502, never a made-up answer. Without `RELAY_URL` it returns 503, so **T-17 must handle that**. The ledger's `peer_questions_answered` = question-log size. Zod mirrors for the new pairing shapes are **deferred to T-17**.

**Acceptance evidence:** `warden/tests/test_l2_end_to_end.py` starts the relay and two Wardens as separate uvicorn processes (own ports, DBs, keys, tokens). They pair with a one-time code; "ok?" → `normal/active_as_usual`; the receipt's `bytes_sent` equals the stored answer's POST body byte for byte; then help → `help/asked_for_help`, and a revoke → `unknown` (still logged). It then dumps the relay DB (raw file + WAL + `iterdump`): no vocabulary words, names, code or public keys (raw/b64/hex). Every blob opens with the right key, so the search ran over the real messages, and no process log contains the code, a name or an answer. `test_reassurance_vocabulary.py`: 15 out-of-vocabulary shapes rejected. With Bob's signal patched to junk, a spy on `seal_for_peer` shows nothing was encrypted and nothing was posted, while the question is still logged as `unknown`. A mutation check (gate disabled) → 21 failures.

**Security-reviewer pass:** no invariant violations. Fixes applied: a malformed relay reply could kill the poller (now strict parsing + a guarded loop, regression-tested); relay body/global caps; a per-peer query cap; key-file mode check; expired pairings pruned on every poll.

**Open, for T-17:** key-fingerprint confirmation on both screens (A7 limit), and an ask cooldown in the UI (A11). Both are done: see the integration note under ¶¶.

**Operational note for T-20:** keep the relay's DB file across restarts. Message ids restart if it is deleted, and Wardens' persisted cursors would then skip messages.

¶¶ T-17 (app/ only): three screens. **People** (`#/people`): paired peers, "Is Anna OK?" (plus a quiet "Home yet?"), and an answer card ("Normal day, just now") with the privacy receipt built from the real `PrivacyReceipt`: "Shared: 1 answer, 212 bytes, encrypted. Location: never." plus the fields and `egress_log_ref`. If `bytes_sent` is 0 (today's Warden placeholder) it says "Nothing left their device" and claims no encryption. **What others can ask about me** (`#/sharing`): a per-person on/off and per-question switches, saved with a `PUT` of the full `rules` list (reverted on error), plus the read-only question log. **Ledger** (`#/ledger`): all 12 CONTRACTS §5 fields, each tagged `data-field`. Home has a quiet "People · Ledger" nav. The mock API serves zod-parsed fixtures (`src/mocks/people.ts`), and `src/api/http.ts` calls `GET /api/people`, `POST /api/people/{id}/ask`, `GET/PUT /api/sharing-rules` and `GET /api/ledger`, zod-parsing each response (an answer outside the vocabulary or `locations_shared ≠ 0` is rejected; tested). Evidence: `pnpm build` ✓, `pnpm test` 65 ✓ (was 45), `pnpm e2e:mock` 6 ✓ (the ask flow + sharing + ledger, each in dark and light, at 390×844 → `app/e2e/results/{people,sharing,ledger}-{dark,light}.png`), and `pnpm e2e` 2 ✓ (the new `ledger.spec.ts` renders the Ledger against a real Warden and compares every count with `GET /api/ledger`). **Open decisions (all settled in the integration note below):** (1) CONTRACTS §5 doesn't give `came_true_rate`'s unit. The app reads it as a 0–1 fraction and compares `1 − came_true_rate` (didn't come true) with Penn State's 91.4%. With no known outcome (`needed_you + never_needed_you = 0`) it shows "No outcomes yet" and makes no claim. T-15 or a contract edit should pin this down. (2) DESIGN §6's "rules approved" and "bytes that left the friend's device" aren't in `LedgerResponse`, so they aren't shown. Add them to §5 first if they're wanted. (3) AGENTS.md's command list should gain `pnpm -C app e2e:mock` (left alone: this task was scoped to app/).

¶¶ **Integration of T-14/T-15 with T-17 (2026-10-01, merged on `main`).**
- **Contracts:** the zod mirrors of `PairingStartRequest`/`Response`, `PairingJoinRequest` and the new `PairingStatusResponse` are in `schemas.ts` and checked by `test_contract_zod_sync.py`.
- **Asking:** People shows calm, honest lines for each Warden status:
  - 503: "can't reach the relay … nothing was asked";
  - 504: "didn't answer in time … asleep or offline … doesn't mean anything is wrong";
  - 502: discarded;
  - 404: not paired any more.
  - The mock's Dad is "asleep", so the 504 line is in the e2e and its screenshots.
- **Cooldown:** 10 minutes per person, enforced by the Warden (`429`, `WARDEN_ASK_COOLDOWN_S`), so it also binds the brain's future `ask_peer`. The app replaces the buttons with "Asked N min ago. They'll tell you if anything changes." (N ≥ 1).
- **Pairing screens:** `#/pair/show` and `#/pair/enter`.
  - The Warden adds `Peer.fingerprint` (8 digits, the same on both devices, computed on read), `pairing_id` and `GET /api/pairing/{id}` so the showing side knows the other phone joined, and `DELETE /api/people/{id}`, which "It doesn't match" uses.
  - Tested: a racing joiner yields a different fingerprint.
- **Decisions:**
  - (1) `came_true_rate` is the 0–1 fraction of closed worries with a known outcome whose fear came true. It is pinned in CONTRACTS §5, and the Ledger route now computes it instead of returning 0.0.
  - (2) DESIGN §6's "rules approved" and "bytes that left the friend's device" stay out of `LedgerResponse` (recorded in §5).
  - (3) AGENTS.md lists `pnpm -C app e2e:mock`.
- **Security-reviewer pass on the pairing UI.** No invariant violations; every finding is fixed and regression-tested:
  1. A racing joiner could get a real answer before anyone compared numbers, while the UI then said "Nothing was shared". Fix: the default rule starts `active: false` until "It matches" calls `POST /api/people/{id}/confirm`, and the copy now says only what's true.
  2. The fingerprint was precomputable from the two static keys. Fix: a joiner nonce in the sealed accept. A relay that also knows the code remains a documented limit (A7).
  3. The cooldown started only on success, and two asks at once both passed. Fix: `last_asked_at` is stamped before sending, under a per-peer lock, and `PeopleListItem` gains `last_asked_at`.
  4. An ask finishing after an un-pair resurrected the peer. Fix: the row is re-read and the write skipped.
  5. The 503 and default copy over-claimed.
  6. Not a security issue: re-pairing hung. Fix: a sealed accept from a known key is now handled, and joining someone you're already paired with is a `409`.

**S7 incident (2026-10-02, night):** a real phone hand-over failed. The model invented the BVG stop id (404 → every dry run failed → parked), triage stored "9:00" as UTC, and the app gave up after 60 s with a wrong message. Fixed with tests:
- BVG stop lookup and pinning;
- Europe/Berlin times;
- `failed` (phase sentence, `POST …/retry`, not in the ledger) separate from `parked`, and no half-built watcher;
- the app follows the real state;
- an hourly forecast.

Details in HANDOFF.md.

## Fri 2 Oct: ship
| ID | Owner | Task | Acceptance / verify | Status |
|---|---|---|---|---|
| T-20 | Claude | `scripts/restart.sh`, error and empty states, recovery after a reboot | Reboot the Brev machine → `restart.sh` → healthy within 5 minutes | doing (restart.sh + recovery done‡‡‡, run at boot by `custody-boot.service`, daily DB backups; a real reboot not run; app error/empty states exist per screen, not reviewed as a set) |
| T-21 | Claude | README: pitch, diagram, quickstart, security model, honest limits | A fresh reader can run `make dev` from the README alone | done (verified from a fresh GitHub clone, 2 Oct; HANDOFF block 11) |
| T-22 | You + Claude | `/demo-check`, then **record the video by 18:00** | Checklist all green | doing: 5 ✅ 4 ◐ 1 ❌ without the phone (HANDOFF block 12) |
| T-23 | You | **Submit by 20:00** | Confirmation received | todo |

‡‡‡ T-20 (2026-10-01, DigitalOcean host): `scripts/restart.sh` brings back docker → `nemoclaw-openshell-gateway` (user service) → the brain sandbox (`nemoclaw start`, then `recover` if 18789 doesn't answer) → refreshes the gateway token (**it rotates on every brain restart**: `scripts/refresh-gateway-token.sh`) → `custody-relay`/`custody-app`/`custody-warden` (systemd user units in `deploy/systemd/`, linger on, installed by `scripts/install-services.sh`) → checks. The Warden's scheduler reconciles watcher sandboxes on start (`Scheduler.reconcile`: `sandbox start` if stopped, recreate from the approved policy + code if gone; tested). Evidence: with every component stopped (no containers, no listeners), `restart.sh` → **HEALTHY in 95 s** (budget 300 s), watcher sandbox back to Ready. A real `reboot` was not run while the owner was away.

## Cut lines (in this order, if behind)
1. Voice input → text only.
2. T-18 web push → in-app alerts only.
3. T-08: 9 adapters → 5 (`http_json`, `web_diff`, `transit_bvg`, `parcel_dhl`, `weather_openmeteo`).
4. T-16: second machine → two Wardens on one machine.
5. T-19 (L3) → one slide in the video.
