# Plan: task board

Owner: **You** = Myron (infrastructure, real usage, video) · **Claude** = code.
Status: `todo · doing · done · cut`. Every task has **acceptance criteria and a check you can run**. An agent works on exactly one task ID at a time.

## Tue 29 Sep: foundation
| ID | Owner | Task | Acceptance / verify | Status |
|---|---|---|---|---|
| T-01 | You | Launch NemoClaw on Brev; onboard the NVIDIA API key | `nemoclaw status` shows the sandbox `Ready` and a healthy inference probe | todo |
| T-02 | You | Turn on OpenClaw's `/v1/chat/completions` endpoint, bound to loopback; create the token | `curl -s localhost:<port>/v1/chat/completions …` returns a completion; the port is not reachable from outside | todo |
| T-03 | Claude | Repo scaffold: structure from AGENTS.md, Makefile, uv, pnpm, ruff/mypy/biome, CI, `.gitignore`, `.env.example` | `make lint typecheck test` passes on the empty skeleton; CI passes | done* |
| T-04 | Claude + You | **SPIKE:** sandbox per watcher. Create from the `watcher_runtime` image → apply the generated policy → exec `run.py` → parse the JSON → delete | Timings recorded in ADR-0001; a request to a host outside the policy is **denied and visible in the logs** | todo |
| T-05 | Claude | App shell on mock data: Home, Hand-over (animated steps + permission card), Worry detail; PWA manifest; design tokens | `pnpm -C app build` passes; a 390×844 screenshot matches the design notes | done† |
| T-06 | You | Start a real worry log (plain notes) to feed in once L1 works | ≥ 5 real worries written down | todo |

† T-05: app shell runs on an in-memory mock API (`app/src/api/client.ts`); fixtures parse through the zod contract schemas. CONTRACTS.md gained `TimelineEvent`, `WorrySummary` and `WorryDetail` to pin down the `/api/worries` response shapes.

\* T-03: `make lint typecheck test` verified locally (evidence in the PR). CI itself is unverified until the first push to GitHub triggers `.github/workflows/ci.yml`.

## Wed 30 Sep: L1 end to end
| ID | Owner | Task | Acceptance / verify | Status |
|---|---|---|---|---|
| T-07 | Claude | Warden core: FastAPI, SQLite, models per CONTRACTS, server-sent events, device-token auth, `/api/health` | pytest covers every route; contract tests compare Pydantic with the zod schemas | done‡ |
| T-08 | Claude | Adapter library v1 (see CONTRACTS §1), each with endpoint declarations and fixture tests | `uv run pytest warden/adapters` passes; the policy generator output snapshots contain no wildcards | done§ |
| T-09 | Claude | Compiler: triage → code generation against adapters → policy generation → dry run → retry ×2 → park | 10 labelled sample worries: ≥ 8 routed correctly; generated watchers pass their dry run | todo |
| T-10 | Claude | Scheduler, act-now alerts, auto-resolve at deadline, the "did it happen?" question | Simulated clock test: silence while `ok`, exactly one alert on `act_now` | done‖ |
| T-11 | Claude | Brain: OpenClaw `custody` skill, standing orders, MCP tool wiring | From chat, "I'm worried X" leads to a Worry appearing in `/api/worries` | todo |
| T-12 | Claude | App wiring for L1: hand-over, permission approval, live status, detail, let-go | Playwright smoke: hand over → approve → status becomes `watching` | done¶ |
| T-13 | You | **Dogfood:** hand over your real worries from the phone | ≥ 6 worry types have been through the full flow | todo |

‡ T-07: all 14 `/api` routes from CONTRACTS §3, aiosqlite persistence, an in-process SSE bus, global bearer auth (incl. `/api/health`, plus `/docs`/`/openapi.json`/`/redoc` disabled per the security-reviewer pass), and `sandboxes_live` computed from the DB. `warden/tests/test_contract_zod_sync.py` diffs every Pydantic/zod pair field-by-field via `z.toJSONSchema`. No compiler/adapters/scheduler (T-08–T-10) — routes that depend on them return honest minimal/zero placeholders, commented inline.

§ T-08: 8 of 9 v1 adapters built — `transit_bvg`, `parcel_dhl`, `weather_openmeteo`, `web_diff`, `http_json` (required) plus `rss`, `ics_calendar`, `flight_status` (stretch, time allowed). `imap_search` deferred: IMAP isn't an HTTP GET call and `Endpoint.method`/`PermissionLine.method` are `Literal["GET"]`, so it needs a new method/protocol literal plus an ADR per AGENTS invariant #2 — out of scope for a library task. `warden/src/warden/compiler/policy.py` generates the OpenShell policy YAML + `policy_summary` from adapter declarations (dedupes identical endpoints, raises on a conflicting `why`); `policies/examples/*.yaml` are the checked-in golden snapshots (95 tests in `warden/tests/adapters`, wildcard-freedom asserted structurally via `Endpoint`/`Adapter` regex constraints and a field validator rejecting bare IP-literal hosts, not just a substring check).

‖ T-10: `warden/src/warden/scheduler.py` with an injectable `Clock` and a `PushNotifier` stub (logs kind + worry id only; T-18 swaps in web push). `ok` → silent (live `watcher.result` SSE only); `act_now` → one alert while the worry is `needs_you`; `resolved` → close, delete the sandbox, ask "Did what you feared happen?" unless the result already says; 3 errors in a row → `paused` (the sandbox is kept for inspection and still counts in `sandboxes_live`) + one notification; deadline → auto-resolve. `next_check_s` is clamped to 300–86400 s. Scheduling state lives in an internal `schedule` table (not a contract). `WARDEN_SCHEDULER=off` disables the loop (the route tests set it). Security-reviewer fixes: a store-wide `write_lock` serialises the scheduler with approve/deny/let-go/outcome; a run claims its next slot *before* exec so no failure can cause 30 s re-runs; stdout is capped at 64 KiB, and `RecursionError`/`ValueError` count as `error`; `evidence` is bounded (source ≤ 64 chars, data ≤ 4 KiB, else `{truncated: true}`) before it is stored. **T-11 must:** pass `last_result` through `compiler/guard.py` (or drop `evidence.data`) before any MCP response reaches the brain. `warden/tests/test_scheduler.py`: 14 simulated-clock tests.

¶ T-12: `app/src/api/http.ts` is the real `/api` client: bearer device token (typed once on the Connect screen, kept in localStorage, never bundled) and every response zod-parsed. `/api/events` is read over `fetch`, not `EventSource`, because EventSource can't send the bearer header. It reconnects with exponential backoff, which resets only after a stream has stayed up ≥ 10 s, and emits a client-only `connected` signal so screens refetch. The mock API is kept behind `VITE_API_MODE=mock` (`pnpm dev:mock`). T-09 doesn't exist yet, so `warden/src/warden/compiler/mock.py` (`CUSTODY_COMPILER=mock`, refused unless `CUSTODY_SANDBOX=mock`) walks new worries to `awaiting_approval` with hand-written GET-only templates. **T-09 deletes it.** `make e2e` runs the Playwright smoke test (hand over → approve → `watching` → let go) against a real uvicorn Warden at 390×844. Merge note (2026-09-30): unified with T-10's `store.write_lock` (was a separate `app.state.worry_lock`) — the same one lock now serialises the scheduler, the mock compiler's check-then-save, and all four write routes (approve/deny/let-go/outcome). `test_let_go_racing_the_compile_save_wins` (mock compiler vs. let-go) and a new `test_scheduler_run_cannot_interleave_with_a_route` (scheduler vs. a write route) both fail if the lock is removed — verified by temporarily deleting it and re-running.

## Thu 1 Oct: L2, Ledger, push
| ID | Owner | Task | Acceptance / verify | Status |
|---|---|---|---|---|
| T-14 | Claude | Relay (ciphertext-only mailbox) plus pairing with a one-time code | Relay database dump contains no plain text (test); pairing works between two local Wardens | todo |
| T-15 | Claude | Reassurance: query/answer, vocabulary enforcement, sharing rules, "normal day" signal v1, privacy receipt | Answers outside the vocabulary are rejected (test); the receipt shows the bytes sent | todo |
| T-16 | You | Second install on the Intel MacBook (Ubuntu) as "Anna" | "Is Anna OK?" answered end to end between the two machines | todo |
| T-17 | Claude | App: People, sharing rules + question log, Ledger | Screenshots; Ledger numbers match `/api/ledger` | todo |
| T-18 | Claude | Web push (VAPID keys) for act-now alerts and approvals | A push arrives on the installed phone app | todo |
| T-19 | Claude | *Stretch, L3:* watcher bundle (code + policy + hash), publish/import, "Borrow a watcher" | An imported watcher runs with **exactly** its declared policy | todo |

## Fri 2 Oct: ship
| ID | Owner | Task | Acceptance / verify | Status |
|---|---|---|---|---|
| T-20 | Claude | `scripts/restart.sh`, error and empty states, recovery after a reboot | Reboot the Brev machine → `restart.sh` → healthy within 5 minutes | todo |
| T-21 | Claude | README: pitch, diagram, quickstart, security model, honest limits | A fresh reader can run `make dev` from the README alone | todo |
| T-22 | You + Claude | `/demo-check`, then **record the video by 18:00** | Checklist all green | todo |
| T-23 | You | **Submit by 20:00** | Confirmation received | todo |

## Cut lines (in this order, if behind)
1. Voice input → text only.
2. T-18 web push → in-app alerts only.
3. T-08: 9 adapters → 5 (`http_json`, `web_diff`, `transit_bvg`, `parcel_dhl`, `weather_openmeteo`).
4. T-16: second machine → two Wardens on one machine.
5. T-19 (L3) → one slide in the video.
