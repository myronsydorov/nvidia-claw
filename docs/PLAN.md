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
| T-07 | Claude | Warden core: FastAPI, SQLite, models per CONTRACTS, server-sent events, device-token auth, `/api/health` | pytest covers every route; contract tests compare Pydantic with the zod schemas | todo |
| T-08 | Claude | Adapter library v1 (see CONTRACTS §1), each with endpoint declarations and fixture tests | `uv run pytest warden/adapters` passes; the policy generator output snapshots contain no wildcards | todo |
| T-09 | Claude | Compiler: triage → code generation against adapters → policy generation → dry run → retry ×2 → park | 10 labelled sample worries: ≥ 8 routed correctly; generated watchers pass their dry run | todo |
| T-10 | Claude | Scheduler, act-now alerts, auto-resolve at deadline, the "did it happen?" question | Simulated clock test: silence while `ok`, exactly one alert on `act_now` | todo |
| T-11 | Claude | Brain: OpenClaw `custody` skill, standing orders, MCP tool wiring | From chat, "I'm worried X" leads to a Worry appearing in `/api/worries` | todo |
| T-12 | Claude | App wiring for L1: hand-over, permission approval, live status, detail, let-go | Playwright smoke: hand over → approve → status becomes `watching` | todo |
| T-13 | You | **Dogfood:** hand over your real worries from the phone | ≥ 6 worry types have been through the full flow | todo |

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
