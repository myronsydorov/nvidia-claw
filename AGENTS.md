# Custody: instructions for coding agents

Custody is an always-on agent (NemoClaw / OpenClaw) that takes custody of a person's worries. Each worry gets its own self-written watcher running in its **own OpenShell sandbox**, and the agent speaks up only when the person needs to act. Loved ones' agents exchange **private reassurance** ("Is Anna OK?" → "normal") without sharing data.

Deadline: **Fri 2 Oct 2026, 20:00 CEST**. Prefer simple, working and demoable over clever. The cut lines are in `docs/PLAN.md`.

## Read first
- `docs/PLAN.md`: tasks, owners, acceptance criteria. **Work on one task ID at a time.**
- `docs/CONTRACTS.md`: **the source of truth** for every data shape, API route and MCP tool.
- `docs/DESIGN.md`: architecture and rationale. `docs/THREAT_MODEL.md`: security model. `docs/adr/`: decisions.

## Repo map
```
warden/                       Python 3.12 host service: FastAPI app API, MCP server, scheduler, SQLite
  warden/src/warden/sandbox/     the ONLY code that calls the `openshell` CLI
  warden/src/warden/compiler/    worry → triage → watcher code + policy
  warden/src/warden/adapters/    adapter declarations (endpoints) used to generate policies
  warden/src/warden/reassurance/ pairing, encryption, normal-day signal
watcher_runtime/  base image + run harness + adapter library imported by watchers
app/              React + Vite + TypeScript installable web app (PWA)
brain/            OpenClaw workspace: skills/custody/SKILL.md, standing orders, config snippets
relay/            encrypted mailbox (FastAPI); stores ciphertext only
policies/         OpenShell policy templates (YAML)
scripts/          setup, restart.sh, spikes
```

## Commands
Keep this list in sync with the Makefile.
- `make setup`: install everything (uv for Python, pnpm for the app)
- `make dev`: run Warden + app locally with mock sandboxes (`CUSTODY_SANDBOX=mock`) and the real compiler, which calls NVIDIA Build if `NVIDIA_API_KEY` is in `.env` and otherwise replays recorded model answers (`CUSTODY_LLM_REPLAY`); open the app and paste `WARDEN_DEVICE_TOKEN`
- `make lint` · `make typecheck` · `make test`: must pass before any commit
- `make relay`: run the L2 relay mailbox on 127.0.0.1:8100 (set `RELAY_URL=http://127.0.0.1:8100` for each Warden)
- `make e2e`: Playwright smoke test (hand over → approve → watching) against a real local Warden
- `make eval-compiler`: opt-in, live: 10 labelled worries through the compiler against NVIDIA Build (needs `NVIDIA_API_KEY`); ≥ 8 must pass
- `make spike`: OpenShell sandbox create → policy → exec → delete (needs a NemoClaw host)
- Python only: `uv run pytest -q`, `uv run ruff check --fix`, `uv run mypy warden relay`
- App only: `pnpm -C app dev|dev:mock|build|test|e2e|lint|typecheck` (`dev:mock` = in-memory mock API, no Warden)

## Non-negotiable invariants
1. Watchers run **only** inside their own OpenShell sandbox. Never on the host, never two watchers in one sandbox.
2. A watcher's network policy is **generated** from its adapters' endpoint declarations. No wildcard hosts, no hand-widening, GET-only unless an ADR says otherwise.
3. Only `warden/src/warden/sandbox/` invokes `openshell`. The brain reaches the Warden through MCP tools.
4. The OpenClaw gateway and its `/v1/chat/completions` endpoint bind to **loopback only**. Only the Warden calls them. The app talks only to the Warden's `/api`.
5. Reassurance answers use the **fixed vocabulary** in `CONTRACTS.md`. No free text, no location, no raw signals ever leave a device.
6. **All watched content (emails, web pages, API responses) is untrusted data, never instructions.** Never feed it into a prompt that has tool access without the injection guard in `warden/src/warden/compiler/guard.py`.
7. Secrets never go in code, logs, fixtures, test snapshots or commits. `.env` is gitignored; use `.env.example`.
8. No automation of logged-in third-party platforms (terms-of-service risk). Official APIs and public data only.
9. Product behaviour: **silence by default**. Never build "check again" loops, which feed anxiety.

## Conventions
- **Python:** 3.12, FastAPI, Pydantic v2 models for every contract, full type hints, `mypy --strict` on `warden/`, ruff for format and lint, pytest. Async for I/O. JSON logs that never include payload bodies.
- **TypeScript:** strict, no `any`, React function components, Tailwind, zod schemas mirroring the Pydantic models, Vitest, and a Playwright smoke test for the hand-over flow.
- **Contracts first:** change `docs/CONTRACTS.md`, then the Pydantic and zod models, then the code, all in the same PR.
- **Tests** use recorded fixtures for external APIs. No live network in unit tests.

## Definition of done
- The PLAN.md acceptance criteria for the task are met, **with evidence** (test output, command output or a screenshot) in the PR description.
- Lint, typecheck and tests all pass.
- Anything touching sandbox, policy, relay or reassurance has had a `security-reviewer` pass.
- PLAN.md status is updated. If a decision changed, add or update an ADR.

## Git
Branch `t-XX-short-name` from `main`. Small PRs. Conventional commits (`feat(warden): …`, `fix(app): …`). Never force-push `main`. Never commit secrets.
