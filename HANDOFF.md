# Handoff: production host bring-up (2026-10-01)

## ⚑ Friday 2 Oct, unattended session (started 08:26 Berlin), live state

### Needs Myron (in order)
_(filled in at the end of the session)_

### Progress
| # | Block | State |
|---|---|---|
| 1 | Stop lookup failure | **done**: cause = BVG's API down (503); lookup now has timeout + 2 retries + disk cache; deployed |
| 2 | Transit defaults | **done**: direction of travel + cancelled or ≥ 10 min, enforced; deployed; image rebuilt |
| 3 | Test health | **done**: 616 Python + 87 app + e2e 2 + e2e:mock 14 all pass; "577" explained (nothing lost); events tests made event-driven; an L2 race fixed; **CI was red on every push (pnpm version) and is now green** |
| 4 | Last night's list | done (status below); added a daily DB backup timer and a boot unit for restart.sh |
| 5 | Layer 2 proof on this server | **done**: paired, fingerprints matched, answered in 0.88 s, rules + log + receipt + cooldown all correct, relay ciphertext only; test peer removed, your state byte-identical. Found and fixed: the app had no "I'm OK" button; relay now on the tailnet for the Mac. Security review: no invariant violations; 3 small fixes applied |
| 6 | Anna on the Mac | **done**: `docs/ANNA_SETUP.md` + `scripts/anna-setup.sh` (setup/start/token/proof/stop), rehearsed here with a throwaway HOME. Not run on a real Mac (needs you) |

### 1. The 08:17 stop lookup failure: BVG's public API was down
Warden log (journal, UTC; 08:17 Berlin = 06:17 UTC). Three hand-overs, each one BVG lookup, each `503`:
```
06:17:03 GET https://v6.bvg.transport.rest/locations?query=Lichtenberg&results=8&poi=false&addresses=false&linesOfStops=true "HTTP/1.1 503 Service Unavailable"
06:17:03 compile failed
06:18:02 GET https://v6.bvg.transport.rest/locations?query=Lichtenberg… "HTTP/1.1 503 Service Unavailable"
06:19:18 GET https://v6.bvg.transport.rest/locations?query=Lichtenberg… "HTTP/1.1 503 Service Unavailable"
```
By hand from the host at 06:27 UTC, 5 tries: `503` after 10.1 s each time (`server: Caddy`, empty body). `/stops/900160004/departures` gives the same 503, so does `v6.db.transport.rest`, and `v6.vbb.transport.rest` hangs past 20 s.
- **Not DNS** (resolves to `thuya.jannisr.de`), **not our firewall** (ufw: allow outgoing), **not a rate limit** (no 429). Its Caddy front end answers, and the upstream behind it times out.
- **Plainly: BVG's hosted API (`*.transport.rest`, a free community service) is flaky and was down this morning.** It worked at 22:52 UTC last night (the S7 dry run passed).
- The old one-shot lookup (15 s timeout, no retry) turned that into an immediate build failure.

**Fix** (`8e026e5`, `eb012c0`): `adapters/bvg_lookup.py`
- 8 s read / 4 s connect timeout;
- 2 retries with 1 s / 3 s backoff on transport errors, timeouts, 429 and 5xx (never on a 4xx);
- every resolved stop is cached in `~/.local/share/custody/bvg_stops.json` (next to the DB, `WARDEN_STOP_CACHE` overrides it). A stop resolved once never needs the network again, and a cached stop name also answers a query without a line.
- The failure sentence now names the real cause: "Looking up the stop failed: BVG's public timetable service isn't answering right now. Nothing was set up; you can try again."
- I seeded the cache with last night's real live answer for Lichtenberg + S7 → `900160004` (the recorded fixture).
- Tests: `test_stop_lookup.py` (503 → timeout → success with backoff `[1.0, 3.0]`; 3×503 gives up after exactly 3 calls; 404 not retried; cached stop with BVG down; not-found not cached; corrupt cache ignored; line-less query) and `test_compiler_pipeline.py::test_bvg_down_is_a_lookup_failure_naming_bvg`.
- **Honest limit:** the cache only saves the *lookup*. A transit watcher still needs BVG's departures endpoint at run time, so while BVG is down a new transit worry fails its dry run (as "the check could not get its data"), and a running one reports `error` (3 in a row → paused, you're told once).
- The two failed 08:16/08:18 worries are `resolved` (you let them go). Untouched.

### 2. Transit defaults
- The runtime has `transit_bvg.disruptions(data, line, toward, min_delay_min=10)`: only departures of that line toward the given end station (`S Potsdam Hauptbahnhof` = `Potsdam Hbf`), only cancelled or ≥ 10 min late. `matched == 0` → the watcher must `fail`, never a silent ok.
- The codegen prompt says to use it. **`codegen.build` enforces it:** a transit watcher that judges departures by hand is sent back for a retry, and so is a `min_delay_min` under 10 unless the worry names that number.
- Tests: `test_transit_defaults.py` (last night's noise → silent; 10 min or a cancellation in my direction → alert; lower threshold only when the worry asks). The recorded live `train` answer predates the rule and is now a test that it gets sent back.
- **Live check** (Nemotron, codegen only, no hand-over, no worry created): "S7 from Lichtenberg to Potsdam Hbf … tomorrow ~9:00" built on attempt 1 with `toward="Potsdam Hbf"`, `min_delay_min=10`, stop from the cache while BVG was down.
- Watcher image rebuilt (`custody-watcher:3ca421840c4e` → `:latest`). Running watchers keep their image, and the change is additive.
- The S7 worry was **not** handed over again.

### 3. Test health
Run at `c431383`, against the current build:
- **Python** `uv run pytest -q`: **616 passed**.
- **App** `pnpm -C app test`: **87 passed** (×3).
- **e2e (real Warden)** `make e2e`: **2 passed**.
- **e2e:mock** `pnpm -C app e2e:mock`: **14 passed**.
- lint ✓, typecheck ✓.

**580 → 577: no tests went away.** The two numbers came from different commands in last night's session log:
- 17:29 UTC: full suite `uv run pytest -q` → `1 failed, 580 passed` (581 collected at `a2a7e39`; the failure was `test_l2_end_to_end`, a race, fixed below).
- 23:06 UTC: `uv run pytest -q warden/tests` → `577 passed`. That run only covers `warden/tests`.
- At that commit (`5ea5dd3`) the full suite was **601** = 577 in `warden/tests` + 24 elsewhere (17 `relay/tests/test_relay.py`, 7 `watcher_runtime/tests`).
- Collected counts per commit (via a worktree) rise monotonically: 458 → 524 → 556 → 561 → 576 → 581 → 589 → 592 → 598 → 599 → 600 → 601.
- The only IDs that disappeared between 581 and 601 were **two renames** when build failures became `failed` instead of `parked`: `test_model_outage_parks_with_an_honest_reason` → `test_model_outage_fails_naming_the_phase`, and `test_three_failures_park_honestly_and_keep_the_failed_watcher` → `test_three_failures_fail_honestly_and_leave_nothing_behind`.

**Flaky tests:**
- `events.test.ts` passed 15/15 alone and 20/20 under 4× parallel load today, so I couldn't reproduce it. The mechanism was real, though: a fixed 5 ms tick in the 401 test, and 1 s wall-clock polls elsewhere. Every wait now resumes on the stream's own callback, with no wall-clock bound. A mutation check (a 401 that retries) fails the test.
- `test_l2_end_to_end` (`'waiting' == 'paired'`) was a **product race**: the peer was listed before its pairing row said done. Both writes and the status read now share one lock. 5/5 green.

**CI was red on every push since T-03** ("No pnpm version is specified", before any test ran). I pinned pnpm 9.15.9, and **CI is green** from `e98dccf` on.

### 4. Last night's list
I found no written list in the repo or the session log, so this is from the evidence on the host:
| Item | State |
|---|---|
| Anna setup + `docs/ANNA_SETUP.md` | **not started** at 09:00 (→ block 6 today) |
| Privacy-proof script | **not started** (→ blocks 5 and 10: `scripts/demo-evidence.sh` dumps the relay) |
| Services enabled at boot | **done** (was partly). `systemctl --user is-enabled`: custody-relay, custody-warden, custody-app, custody-ufw-brain.timer, nemoclaw-openshell-gateway = enabled; system docker and tailscaled = enabled; Linger=yes. The brain sandbox and gateway-token refresh only came back via a manual `restart.sh`; the new **`custody-boot.service`** (enabled) runs it at boot. Started under systemd just now → `HEALTHY in 30s`, Result=success. **No reboot was run.** |
| Database backup | **done** (was partly: two manual snapshots). **`custody-backup.timer`** (daily + 10 min after boot) → `~/.local/share/custody/backups/{warden,relay}-<UTC>.db`, online backup + integrity check, keeps 14. First run 06:55 UTC ✓. Manual snapshots: `warden.db.bak-20261002-s7`, `warden.db.bak-20261002-0835`. |
| README | **partly**: pitch and the ADR-0003 limit are there; the quickstart says "Filled in by task T-21" (→ block 11) |

### 5. Layer 2 proof on this server (06:56–07:08 UTC)
A clearly labelled **test Warden "TEST-Anna"** ran on `127.0.0.1:8010` with its own data dir (scratchpad, `CUSTODY_SANDBOX=mock`, compiler and scheduler off, `CUSTODY_ACTIVITY=off`), the same relay, and its own key and token. **Your** Warden named it "TEST Anna (L2 proof, remove)". DB backups were taken first (`backups/*-20261002-065637.db`).

| Step | Evidence |
|---|---|
| Pairing code | real `POST /api/pairing` → `HSNXYQ1Y`; TEST-Anna `POST /api/pairing/join` → 200; real `GET /api/pairing/{id}` → `paired` after **2.4 s** |
| Fingerprints | **`8013 1826` on both sides**; both `POST …/confirm` → 204 |
| Sharing rules | TEST-Anna's rule for Myron: `active:false` before confirm → `active:true` after |
| Signal | headless, no history → `unknown/not_enough_data`; after `POST /api/me/check-in` → `normal/active_as_usual` |
| **"Is Anna OK?"** | `{"level":"normal","reason":"active_as_usual"}` in **0.88 s** |
| Privacy receipt | `{"bytes_sent":316,"fields_shared":["level","reason","ts"],"location_shared":false,"egress_log_ref":"relay:4"}`. 316 = the POST body exactly (base64 of the 184-byte ciphertext = 248 chars, plus 36 bytes of JSON and a 32-char key id) |
| Cooldown | 2nd ask at once → **429** "asked less than the cooldown ago"; `last_asked_at` not restamped by the 429; the next ask at 07:07:20 (10 min + 3 s) → 200 |
| Rules withhold | TEST-Anna turned sharing off → the ask got `unknown/not_enough_data`, **same 316 bytes**, still written to her question log |
| Question log (TEST-Anna) | `ok → normal` 06:57:18, `ok → unknown` 07:07:21 |
| **Relay = ciphertext only** | 6 rows (offer, sealed accept, 2× query, 2× answer). Columns `id, recipient, sender, ciphertext, ts`, with key ids only. Entropy 6.5–7.1 bits/byte on 140–245-byte blobs. **No** names, code, vocabulary words or public keys (raw, b64 or hex) in any row or in the raw DB file + WAL |
| Cleanup | `DELETE /api/people/…` on both sides (204), TEST-Anna stopped, its data dir deleted. Your `/api/people`, `/api/ledger`, `/api/sharing-rules` are **byte-identical** to before. One completed pairing row (no key) stays ≤ 1 h by design and is pruned automatically; it's invisible in the app and ledger. The relay's 6 ciphertexts expire in 24 h |

**What broke, fixed:**
- **The app had no way to say "I'm OK".** `/api/me/check-in`, `/api/me/help` and `/api/me/signal` existed, but no screen used them. A fresh second machine (< 3 days of activity history) therefore honestly answers "Not enough to say", which would sink the video's "Normal day" beat. "What others can ask about me" now opens with **Right now** (what an allowed person would hear) plus **I'm OK** (3 h) and **I need help / I'm fine again** (`c8ff556`, test in `http.test.ts`).
- **The relay was loopback-only**, so the Mac couldn't reach it. It's now served at `https://ubuntu-s-4vcpu-8gb-fra1.tail081ca8.ts.net/relay` (tailscale serve, **tailnet only**, no Funnel; the public IP still refuses :443). `install-services.sh` does this.
- **Poller log spam**: 1,793 of the Warden's last 1,964 journal lines were the 2 s mailbox polls, which buried the BVG 503s. Successful polls are no longer logged (`e673e6d`).

---

## ⚑ Tonight (2026-10-02, ~00:50 Berlin): the S7 hand-over failure, fixed

### Root cause (from evidence: Warden DB rows, timeline, generated code, BVG API)
The worry `w_01M3WRWXXECE3Y8F1JZVV64NKS` failed in the **compile → dry-run (testing) phase**, not at permission time.
1. **Triage, 22:20:59 UTC.** It got only the UTC time and returned the fear "…around 09:00 UTC" with deadline `2026-10-02T09:00Z`, two hours late, because the person meant 09:00 Berlin.
2. **Codegen.** It wrote `STOP_ID = "8011120"` from memory, giving the card `GET v6.bvg.transport.rest/stops/8011120/departures`. BVG answers that id with `{"code":"NOT_FOUND","hafasCode":"LOCATION","message":"LOCATION: location/stop not found"}`. The real stop is `900160004` (S+U Lichtenberg Bhf).
3. **Dry run, 3 attempts.** `transit_bvg.fetch` got the 404, so run.py reported `status: error` each time. After the 3rd attempt the worry was set to `parked` at 22:23:02 ("I couldn't build a watcher that works…"), and a `dry_run_failed` watcher row (`cw-bjasgm4b`) was kept.
   - That sandbox **never existed**: dry runs use throwaway `cwd-*` sandboxes, and all were deleted. The app showed "What it checks" and "Its jail" only because of the leftover row.
4. **The phone's "Something went wrong… Nothing was set up."** That came from the **app**: `handOver` gave up after a fixed 60 s, while the Warden kept going for about 2 min and then parked the worry. So the message didn't match the real state.
- The Warden logs didn't show the per-attempt reasons, because the JSON log fields are dropped by the default formatter. The DB rows and code were enough. A follow-up would be a JSON log formatter.

### Fixes (each with a test; all pushed)
| # | Fix | Test |
|---|---|---|
| 1 | **Stop ids come from a real lookup.** The model names the stop as the person wrote it, plus the line. The Warden resolves it at compile time via BVG `/locations`, requiring the stop to serve that line, then pins the id into the declared path (so into the policy and the card) and into run.py (`BVG_STOP_ID` placeholder). A numeric id is accepted only if the person wrote it. `transit_bvg.fetch` gains `when`/`duration_min` for a later trip, and `delay_s` is `0`, not `null`. | `test_stop_lookup.py`: the invented `8011120` is refused; "Lichtenberg"+S7 → `900160004` "S+U Lichtenberg Bhf (Berlin)" (recorded fixture). Live: S7 departures toward "S Potsdam Hauptbahnhof" at 09:06, 09:16… |
| 2 | **Times are Europe/Berlin.** Triage gets the Berlin local time and returns the local deadline with no offset; *our* code converts it (naive → Europe/Berlin → UTC). The fear text uses local time. Codegen is told both. The app formats with `timeZone: Europe/Berlin`. | `test_compiler_triage_codegen.py` (CEST and CET), app `lib.test.ts` (run with `TZ=America/New_York`) |
| 3 | **No present-tense check or jail without a running watcher.** "What it checks" and "Its jail" show only for an active/paused watcher, and "What it would check" before approval. A failed build saves **no** watcher row. `cw-bjasgm4b` never existed. | `test_compiler_pipeline.py` (no watcher row, no live sandbox after a failure), e2e `worries.mock.spec.ts` |
| 4 | **`parked` ≠ build failure.** `parked` now means it can't be watched by nature, or it needs something from you. A build failure is `failed`, with one sentence naming the phase (understanding / writing / stop lookup / testing + what the test hit), e.g. "Testing the watcher failed: the check could not get its data. Nothing was set up; you can try again." There is a **Try again** button (`POST /api/worries/{id}/retry`, CONTRACTS §3), and build failures are excluded from all ledger totals (CONTRACTS §5). | pipeline tests, `test_worries.py` (retry, 409, ledger) |
| 5 | **The app shows the real state.** It follows the worry until it settles (events + a 15 s poll, no 60 s give-up) and shows the card, "Parked." with its reason, or the failed sentence with Try again. "Nothing was handed over" appears only when the POST itself failed. | `http.test.ts` (resolves past 2 min; parked/failed resolve with their real state) |
| + | Weather: an hourly forecast in Berlin time with its offset, so "16:00–19:00" can be checked. | `test_weather_openmeteo.py` |
| + | "What if I don't win the challenge?" is a labelled eval case with a recorded live answer: `uncontrollable → park` (2/2 live). | `test_compiler_recorded_live.py` |

Checks: `make lint` ✓ · `make typecheck` ✓ · `make test` 600 Python + 87 app ✓ · `pnpm e2e:mock` 14 ✓ · `make e2e` (real Warden) 2 ✓.

### The earlier failed attempt
`w_01M3WRWXXECE3Y8F1JZVV64NKS` got **one appended timeline event** (`failed`, "Marked as a failed build… Not counted in your ledger.") using `scripts/mark_build_failure.py`. Nothing else changed: its status is still `parked`, and its text, resolution, history and watcher row are untouched. DB backup: `~/.local/share/custody/warden.db.bak-20261002-s7`. Ledger before → after: `worries_total` 2 → 1 (now 5 with tonight's worries).

### Tonight's hand-overs (real API, one at a time, none approved)
| Worry | State | Card / reason |
|---|---|---|
| S7 Lichtenberg → Potsdam Hbf, ~9:00 | **awaiting your approval** (40 s) | `GET v6.bvg.transport.rest/stops/900160004/departures`. Fear "…Fri 2 Oct 2026 around 09:00…", deadline 09:00 Berlin (07:00Z). It checks 08:45–09:30 Berlin every 5 min. *Caveats:* it doesn't filter by direction (an Ahrensfelde-bound S7 delay would also alert) and alerts on delays over 1 min. Deny and retry if you want it stricter. |
| Rain in Berlin, 16:00–19:00 | **awaiting your approval** (40 s) | `GET api.open-meteo.com/v1/forecast`. Deadline 19:00 Berlin. Hourly precipitation for 14:00–17:00 UTC (= 16–19 Berlin), every hour. |
| GitHub down this evening | **awaiting your approval** (30 s) | `GET www.githubstatus.com/api/v2/status.json`. Deadline 23:59 Berlin; status indicator ≠ `none` → alert. |
| "What if I don't win the challenge?" | **parked** (5 s) | uncontrollable → weekly worry time. No watcher, no sandbox. |

No orphan sandboxes: only `custody-brain` and `cw-76epww8s` (the approved school-calendar watcher). The three cards get their sandboxes only when you tap Allow.

### Morning, for you
1. On your phone, open each card and **Allow** or **Deny**: S7 (before ~08:45!), rain, GitHub. Pull to refresh if the app was open overnight; it needs the new build (it's served already).
2. The old S7 attempt still shows on Home as "Parked". Let it go if you like (it isn't counted).
3. A T-11 test worry, "I'm worried my friend Lena is annoyed with me after what I said at the T-11 test dinner." (parked), is on Home. Let it go.

### T-11 (brain) is now done: there was a second blocker, ufw
Tailscale Serve is enabled (`/` app, `/api`, `/mcp`, tailnet only), and the brain's MCP registration showed `trustedPrivateTarget: match`. Even so, the first chat test created **no** worry. `nemoclaw custody-brain mcp status custody` showed `curl: (28) Connection timed out`, and the kernel log showed `[UFW BLOCK] IN=br-82185a31c7df SRC=172.18.0.2 DST=100.81.50.38 DPT=443`.
- **Cause:** ufw's default deny dropped the brain container's packets to the tailnet IP.
- **Fix:** `scripts/ufw-brain-mcp.sh` adds exactly one rule (`ALLOW IN on br-82185a31c7df from 172.18.0.2 to 100.81.50.38 port 443/tcp`, tagged `custody-brain-mcp`). It is idempotent, replaces itself if the container IP or bridge changes, and is called by `restart.sh` and `install-brain.sh`. ufw stays on with default deny, and nothing public changed.
- **After the fix:** the probe shows `credential resolution: verified (HTTP 200)`. A chat through the loopback gateway created worry `w_01M3WV2BR1ABGXMJ51ZGGMB5HG` in `/api/worries` (parked, as a social worry). **The T-11 acceptance is met.**
- **Behaviour fix:** while blocked, the brain had *claimed* "I've taken your worry" without any tool call. A new standing order (#7) and the skill now say: only claim what `hand_over` confirmed, and say plainly when a tool fails. Both are reinstalled in the brain.
- `restart.sh`: HEALTHY in 38 s, with the ufw step included.
- **Security review of tonight's commits:** none of the 9 invariants is violated. Fixed:
  - (Medium) `ufw-brain-mcp.sh` aborted after the first delete (`yes | ufw delete` under `pipefail`), and its partial-match IP comparison could keep an old allow for a lookalike IP. It now compares fields exactly, uses `ufw --force delete`, and removes old rules even when the brain is down. Verified: a planted `172.18.0.23` rule was removed, leaving exactly one rule.
  - (Low) A 2-minute `custody-ufw-brain.timer` re-pins the rule if the brain restarts on its own.
  - (Low) Only stop names that appear in the worry (≤ 80 chars) are sent to the BVG lookup.

---

Host: DigitalOcean `ubuntu-s-4vcpu-8gb-fra1`, Ubuntu 24.04, user `myron`, ufw on, Tailscale up (`100.81.50.38`).
NemoClaw v0.0.124 · OpenShell 0.0.116 · OpenClaw v2026.7.1 · brain sandbox `custody-brain`.

## Status
| Task | State |
|---|---|
| A. NemoClaw healthy | done |
| B. T-02 gateway chat endpoint (loopback) | done |
| C. T-04 OpenShell SandboxDriver | done (security-reviewed, hardened) |
| D. Deploy (systemd + tailscale serve, T-20 restart.sh) | done: https://ubuntu-s-4vcpu-8gb-fra1.tail081ca8.ts.net/ (tailnet only) |
| E. T-11 brain | **done** (2026-10-02): chat → MCP `hand_over` → worry in `/api/worries` |

## A. NemoClaw healthy: done
`nemoclaw custody-brain status` (abridged):
```
  Sandbox: custody-brain
    Model:    nvidia/nemotron-3-super-120b-a12b
    Provider: nvidia-prod
    Inference: healthy (https://inference.local/v1/models)
    Inference (route reachability): reachable (https://inference.local/v1/models)
    OpenShell: 0.0.116 (docker)
  Phase: Ready
```
NemoClaw's own upstream probe is skipped (it wants `NVIDIA_INFERENCE_API_KEY` in the CLI's env), so I
proved the upstream with a real completion from inside the sandbox through the gateway's inference route:
```
$ nemoclaw custody-brain exec -- curl -s https://inference.local/v1/chat/completions -d '{"model":"nvidia/nemotron-3-super-120b-a12b","messages":[{"role":"user","content":"Reply with exactly: pong"}]}'
{"id":"chatcmpl-a2e0…","choices":[{"index":0,"message":{"content":"pong",…},"finish_reason":"stop"}],…}
```
`nemoclaw custody-brain doctor` → `Summary: healthy` (Docker 29.1.3, gateway connected, sandbox Ready, route nvidia-prod).
No firewall/Docker-bridge fix was needed.

## B. T-02 gateway chat endpoint: done
- Enabled with one key: `openclaw config set gateway.http.endpoints.chatCompletions.enabled true`, then
  `nemoclaw custody-brain gateway restart` (steps in `brain/gateway.md`).
- Token: `~/.config/custody/gateway.env` (0600, outside git; `OPENCLAW_GATEWAY_URL`, `OPENCLAW_GATEWAY_TOKEN`), written from
  `nemoclaw custody-brain gateway-token` without echoing.
- Bind: OpenShell forwards the gateway to `127.0.0.1:18789` only; ufw has no rule for it (default deny incoming).

`scripts/check-gateway.sh`:
```
ok: loopback completion: "content":"pong"
ok: no token -> 401
ok: :18789 listens on loopback only
ok: refused on 157.230.119.152:18789      (public IP)
ok: refused on 10.19.0.5:18789
ok: refused on 10.114.0.2:18789
ok: refused on 172.17.0.1:18789
ok: refused on 100.81.50.38:18789         (tailnet)
ok: refused on 172.18.0.1:18789
```

## C. T-04 real OpenShell SandboxDriver: done
- **Driver:** `warden/src/warden/sandbox/openshell.py`. It creates the sandbox network-less (baseline policy), runs `policy set --wait` with the generated policy, uploads `/w/run.py`, execs it and deletes the sandbox. `ensure_running` brings a sandbox back after a reboot, and `denials()` reads the OCSF `DENIED` log lines. It only accepts `cw-*`/`cwd-*` names, so it can never touch `custody-brain`.
- **Policy:** `compiler/policy.py` now emits OpenShell's real schema (L7 `rest`/`enforce` GET rules, `/usr/local/bin/python3.12` only, Landlock strict). Snapshots are in `policies/examples/`.
- **Image:** `watcher_runtime/image/Dockerfile` (base pinned by digest, hash-pinned deps, runtime wheel), built with `make watcher-image`.
- **Percent-encoding decision:** I measured OpenShell with raw request targets. It canonicalizes the path, decoding `%40`→`@` but keeping `%23`, `%20` and `%25`, then matches it literally. So `Endpoint.path` must be in that canonical form (`adapters.base.canonical_path`), and `*`, `;`, `%2F`, `%5C`, dot and empty segments are refused. The Google Calendar ICS link now works. Details are in ADR-0001 and CONTRACTS §1.
- **Security-reviewer:** no invariant violations. All findings are fixed and tested:
  - a public-address check on worry hosts, at compile and at approve;
  - port 443 only;
  - an env allowlist for the CLI;
  - an exact-shape policy check;
  - collision-free policy keys;
  - re-uploading `run.py` before every run;
  - the pinned image;
  - `fullmatch` for names and paths;
  - cleanup when a create fails.

`make spike` (live, through the driver):
```
permission card:
  GET api.open-meteo.com/v1/forecast  (check the weather forecast)
  GET calendar.google.com/calendar/ical/en.german%23holiday@group.v.calendar.google.com/public/basic.ics  (check the holiday calendar)
WatchResult parsed: status=ok summary='spike probe finished'
  [ok ] declared: open-meteo /v1/forecast          -> ok
  [ok ] declared: Google ICS, percent-encoded      -> 200
  [ok ] undeclared host: example.com               -> ProxyError
  [ok ] undeclared path: open-meteo /v1/archive    -> 403
  [ok ] encoded slash                              -> RemoteProtocolError
OpenShell denial log (3 lines):
  … NET:OPEN [MED] DENIED /usr/local/bin/python3.12(34) -> example.com:443 [policy:- engine:opa] [reason:endpoint example.com:443 is not allowed by any policy]
  … HTTP:GET [MED] DENIED GET http://api.open-meteo.com:443/v1/archive [policy:custody_api_open_meteo_com_443_ba8e8afe engine:l7] [reason:L7_REQUEST deny …
  … NET:OPEN [MED] DENIED api.open-meteo.com:443 [… engine:l7] [reason:HTTP request-target rejected: request-target contains an encoded '/' (%2F) …
timings: create → Ready 1.07 s · RAM idle 12.22MiB · policy set --wait 9.14 s · upload 0.09 s · exec 5.46 s · delete 0.40 s
```
Checks: `make lint` ✓ · `make typecheck` ✓ · `make test` 561 Python + 83 app ✓.

**Live L1 end to end on the deployed Warden** (`CUSTODY_SANDBOX=openshell`, live NVIDIA Build). I handed over the school-calendar worry. It went triaging → compiling (with a real dry run in a `cwd-*` sandbox) → awaiting_approval, with the card `GET calendar.google.com/…/de.german%23holiday@group.v.calendar.google.com/public/basic.ics`. I approved it via `/api`, which created the sandbox `cw-76epww8s` (Ready). The first scheduled run returned `ok | No change in the school calendar.` That worry is still live; let it go in the app if you don't want it.

## D. Deploy: services up on loopback; tailnet URL blocked on you
- **systemd user units** (`deploy/systemd/`, installed by `scripts/install-services.sh`, linger on so they start at boot):
  - `custody-relay` on 127.0.0.1:8100;
  - `custody-warden` on 127.0.0.1:8000 (`CUSTODY_SANDBOX=openshell`);
  - `custody-app` on 127.0.0.1:8300 (`app/dist`).
- **Environment:** `.env` (NVIDIA key) → `~/.config/custody/gateway.env` → `~/.config/custody/warden.env`, all 0600 and outside git. The **device token** is generated in `warden.env`; get it with `grep WARDEN_DEVICE_TOKEN ~/.config/custody/warden.env`.
- **Nothing new is exposed:** all three bind to 127.0.0.1, ufw is unchanged, there is no Funnel, and `/api` without the token returns 401.
- **`tailscale serve` is blocked:** "Serve is not enabled on your tailnet" (see Blocked). Once you approve it, `scripts/install-services.sh` maps `https://ubuntu-s-4vcpu-8gb-fra1.tail081ca8.ts.net/` → app and `/api` → Warden.
- **T-20:** `scripts/restart.sh`. It stops nothing, starts everything in order, refreshes the rotating gateway token, and the Warden reconciles watcher sandboxes. From a full stop (0 containers, 0 listeners):
```
[  2s] ok: OpenShell gateway connected
[ 77s] ok: brain sandbox Ready
[ 77s] ok: OpenClaw gateway on 127.0.0.1:18789
    gateway token refreshed in /home/myron/.config/custody/gateway.env
[ 84s] ok: relay /v1/health · ok: app on 127.0.0.1:8300 · ok: warden /api/health
    ok: loopback completion: "content":"pong" … refused on every non-loopback address
[ 90s] warden: {"status":"ok","sandboxes_live":1}   (cw-76epww8s back to Ready)
[ 95s] HEALTHY in 95s (budget 300s)
```

## E. T-11 brain: built; the last hop is blocked on Tailscale Serve
- **Warden MCP server** (`warden/src/warden/mcp_server.py`) at `/mcp/`: Streamable HTTP, stateless JSON, official MCP SDK 2.2.0.
  - **Tools:** the seven CONTRACTS §4 tools (`hand_over`, `list`, `get`, `let_go`, `record_outcome`, `ask_peer`, `ledger`). **There is no approval tool**, and the in-process dispatch can only reach an allowlist of `/api` routes; ids must fullmatch `w_<ulid>`/`p_<ulid>`.
  - **Auth:** its own token, `WARDEN_MCP_TOKEN`, in `warden.env`. It must differ from the device token; the device token gets 401. Host headers outside the allowlist get 421.
  - **Guarded output:** watcher results go through `guard.guard_watch_result` (`evidence.data` dropped). Timeline texts and `resolution` are wrapped in `<untrusted_data>`. Code and policy YAML are never returned.
  - Tests: `warden/tests/test_mcp.py` (15).
- **Brain** (installed by `scripts/install-brain.sh`, idempotent):
  - the `custody` skill is in the sandbox, and `nemoclaw custody-brain skill list` shows it `✓ ready`;
  - the standing orders are appended to the workspace `AGENTS.md` as a marked block (2 marker lines found).
- **Live check on loopback** (the deployed Warden):
```
no token: 401
device token: 401
mcp token, tools: ['hand_over', 'list', 'get', 'let_go', 'record_outcome', 'ask_peer', 'ledger']
list -> "summary": "<untrusted_data source=\"watcher_summary\" nonce=…>\nNo change in the school calendar.\n</untrusted_data …>"
```
- **Why blocked:** NemoClaw only registers HTTPS MCP servers (`nemoclaw … mcp add --url https://…`), and the sandbox can't reach host loopback. The clean route is the tailnet HTTPS name, which resolves to a CGNAT address and is admitted with `--trusted-private-host`; that needs Tailscale Serve. `scripts/install-brain.sh` stops at that step with the approval link (exit 2). After you approve Serve, re-running it does `tailscale serve /mcp`, then `nemoclaw custody-brain mcp add custody --url https://ubuntu-s-4vcpu-8gb-fra1.tail081ca8.ts.net/mcp/ --env CUSTODY_MCP_TOKEN --trusted-private-host …`. The token goes into OpenShell's provider store, and the sandbox sees only a placeholder.
- **Security-reviewer pass on T-11:** no invariant violations. Fixed:
  - (M1) `hand_over` over MCP refuses links and domains. Otherwise content the brain read could make a dry-run sandbox GET an attacker's host before any approval. Links go through the app. It is also capped at 10 per hour, and this is THREAT_MODEL A12.
  - (L1) `evidence.source` is now wrapped as untrusted data.
  - (L2) `/mcp/` refuses non-HTTP scopes.
  - Open informational items: (I1) `--trusted-private-host` admits the whole tailnet name, so the brain could also reach `/api`, but that still needs the device token, which it doesn't have; scope it to `/mcp/` if NemoClaw allows. (I2) Check once that `nemoclaw mcp add` output never echoes the token.
- **Acceptance still open:** "from chat, 'I'm worried X' → a Worry in `/api/worries`" needs that hookup. The MCP half is proven (`test_hand_over_puts_a_worry_in_the_api`).

## Decisions made
- I did not read the brain's `openclaw.json` (it holds secrets; the read was refused by the permission guard). I changed only the one key via `openclaw config set`.
- Fixed a flaky app test (`events.test.ts` used a fixed 5 ms sleep; now polls up to 1 s). Baseline after: 458 Python + 83 app tests pass.
- Installed on the host: `uv` (~/.local/bin), `pnpm@9` (npm -g), `make`, `xprintidle`.
- **Not a real reboot:** T-20 was proven by stopping every component (gateway, brain, watcher, services), not with `reboot`, because you couldn't recover the host if it didn't come back.
- **Units:** the Custody units are systemd *user* units, like NemoClaw's own `nemoclaw-openshell-gateway.service`, with linger enabled.
- **App server:** the app is served by `python3 -m http.server` on loopback behind `tailscale serve`. The Warden doesn't serve static files, and the app uses hash routes, so no SPA fallback is needed.
- **Headless signal:** `CUSTODY_ACTIVITY=off` on this server (there is no desktop idle time), so the "normal day" signal relies on check-ins.
- **`/w` stays writable:** OpenShell can't narrow a live sandbox's filesystem, so the scheduler re-uploads the approved `run.py` before every run instead.
- **`.claude/settings.json`:** the security-reviewer noticed your uncommitted local edit, which removes the openshell/nemoclaw deny rules. As you asked, I didn't commit it and didn't revert it. Consider restoring it when you're done on this host.
- Git identity for this repo set to match history (`Myron Sydorov <bymyronsydorov@gmail.com>`); the very first handoff commit used `sydorov.myron@gmail.com`.

## Blocked
- **Tailscale Serve is not enabled for the tailnet.** `tailscale serve` prints "Serve is not enabled on your tailnet. To enable, visit: https://login.tailscale.com/f/serve?node=nZtmGMpseH11CNTRL" and then waits. Only a tailnet admin can approve it. I did not add any HTTP or public fallback.

## Owner: do this next
1. **Enable Tailscale Serve** for the tailnet (one click as admin): https://login.tailscale.com/f/serve?node=nZtmGMpseH11CNTRL (HTTPS certificates must be on).
2. On the host: `cd ~/nvidia-claw && scripts/install-services.sh`. That sets up `tailscale serve` for `/` → app and `/api` → Warden. Then the app is at **https://ubuntu-s-4vcpu-8gb-fra1.tail081ca8.ts.net/** (tailnet only).
3. Open that URL on your phone (in the tailnet), paste the device token from `grep WARDEN_DEVICE_TOKEN ~/.config/custody/warden.env`, then Add to Home Screen.
4. `scripts/install-brain.sh`: registers the Warden's `/mcp/` with the brain. Then test T-11: chat "I'm worried my DHL parcel won't arrive by Friday" (`nemoclaw custody-brain agent …` or the gateway chat endpoint) and check that a worry appears in the app or `/api/worries`. Also check that `nemoclaw custody-brain mcp status custody --json` reports `trustedPrivateTarget.state = match`.
5. Optional: a real `sudo reboot`, then `scripts/restart.sh`, to prove T-20 on a true reboot. A full stop/start was proven: HEALTHY in 95 s.
6. A DHL key for `parcel_dhl` needs an OpenShell provider attached at sandbox create. That isn't wired yet (follow-up in ADR-0001).
7. The school-calendar test worry is live (`cw-76epww8s`). Let it go in the app if you don't want it.
8. Restore your `.claude/settings.json` deny rules when you're done on this host. I left the file uncommitted and unchanged, as you asked.
