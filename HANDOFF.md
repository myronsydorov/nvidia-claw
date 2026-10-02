# Handoff: production host bring-up (2026-10-01)

## ⚑ Friday 2 Oct, unattended session (08:26–10:00 Berlin): summary

**Done:** all 12 blocks. Everything is deployed, `restart.sh` → HEALTHY, CI is green, and the security review found no invariant violations.
- 621 Python and 93 app tests, `make e2e` 2, `e2e:mock` 14, all passing.

**Failed, or not possible from here, and why:**
- **The 08:17 failure was BVG's public API being down** (`503` from `*.transport.rest`; back at 09:50). It wasn't our bug, but the one-shot lookup made it fatal. That is fixed: retries plus a stop cache.
- **No real worry has produced `act_now` yet.** The alert path is proven only on a separate test Warden.
- **"Is Anna OK?" between two machines** isn't done; it needs your Mac. It is proven between two Wardens on this host.
- **The iPhone check** (status bar, home-screen icon) needs your phone.
- **A real reboot** was not run (you asked me not to). The new boot unit was started under systemd instead.

**Your real ledger now:**
- Handed over **5**, still watched **3**, watchers built **4**, sandboxes live **3**.
- **0** outcomes known, so the app shows "No outcomes yet" and no 91.4% comparison.
- **0** questions about you, **0** locations shared.
- Not counted: 3 build failures (S7) and 1 test worry (Lena, T-11).

### Needs Myron (in this order)
1. **Phone, 5 min:**
   - Delete the Custody icon from the home screen, open the tailnet URL in Safari, then Share → Add to Home Screen. iOS caches the old icon.
   - Check that the clock no longer overlaps content when you scroll, and look at dark and light mode.
   - On Home, **Let it go** on the two misleading rows under "For worry time": the night's S7 (a build failure) and "Lena … T-11 test dinner".
2. **Mac, 15 min:** follow `docs/ANNA_SETUP.md`:
   - `git pull`, then `./scripts/anna-setup.sh`, then `./scripts/anna-setup.sh start`;
   - pair your phone (Show a code) with the Mac (Enter their code), compare the 8 digits, tap It matches on both;
   - on the Mac, tap **I'm OK**;
   - on the phone, ask **Is Anna OK?**;
   - then run `./scripts/anna-setup.sh proof`.
   - **Without "I'm OK", a fresh Mac honestly answers "Not enough to say".**
3. **Decide the video script** (DESIGN §8 mismatches are listed under block 12 below). Mainly:
   - there's no DHL key for the parcel scene;
   - "U8 strike" can't be watched as written;
   - the hook's 91% must be said as research;
   - there's no real `act_now` yet.
4. **The act_now scene:** either show the test-Warden screenshots in `~/custody-evidence/alert-path/`, **labelled as a test**, or film a real alert if one fires (rain 16:00–19:00). Never present the test as real usage.
5. **Just before recording**, ask "Is Anna OK?" once, then run `./scripts/demo-evidence.sh` on the host (fresh relay rows, a live denial, the sandbox list). It takes about 25 s and prints no secrets.
6. **Record by 18:00, submit by 20:00** (T-22, T-23).
7. Optional, after submitting:
   - a Tailscale ACL limiting `tcp:443` on this node to your devices (THREAT_MODEL A6);
   - Ledger "endpoints denied" could be wired to the OpenShell log.

### Progress
| # | Block | State |
|---|---|---|
| 1 | Stop lookup failure | **done**: cause = BVG's API down (503); lookup now has timeout + 2 retries + disk cache; deployed |
| 2 | Transit defaults | **done**: direction of travel + cancelled or ≥ 10 min, enforced; deployed; image rebuilt |
| 3 | Test health | **done**: 616 Python + 87 app + e2e 2 + e2e:mock 14 all pass; "577" explained (nothing lost); events tests made event-driven; an L2 race fixed; **CI was red on every push (pnpm version) and is now green** |
| 4 | Last night's list | done (status below); added a daily DB backup timer and a boot unit for restart.sh |
| 5 | Layer 2 proof on this server | **done**: paired, fingerprints matched, answered in 0.88 s, rules + log + receipt + cooldown all correct, relay ciphertext only; test peer removed, your state byte-identical. Found and fixed: the app had no "I'm OK" button; relay now on the tailnet for the Mac. Security review: no invariant violations; 3 small fixes applied |
| 6 | Anna on the Mac | **done**: `docs/ANNA_SETUP.md` + `scripts/anna-setup.sh` (setup/start/token/proof/stop), rehearsed here with a throwaway HOME. Not run on a real Mac (needs you) |
| 7 | Alert path | **done**: the app had no alert card and never asked "did it happen?"; both built, then proven end to end with a real sandbox on a separate TEST Warden, which was then removed |
| 8 | Ledger truth | **done**: real numbers below; the T-11 test worry is no longer counted; unmeasured tiles are labelled; 91.4% is labelled research |
| 9 | App polish | **done** (desktop-verified): status-bar strip, PNG home-screen icons + manifest, names keep capitals, 2 wording fixes; dark + light, no console errors. **Check on the iPhone** (Needs Myron) |
| 10 | Evidence script | **done**: `scripts/demo-evidence.sh`, 5 sections all ✔ live, ~25 s |
| 11 | README (T-21) | **done**: quickstart verified from a fresh GitHub clone; architecture diagram; real / simulated / cut; ADR-0003 limit; judging criteria |
| 12 | Demo check | **done**: 5 ✅, 4 partly, 1 ❌ (details below) |

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

### 7. Alert path
**What was missing:**
- A `needs_you` worry was only a row with a dot. The detail showed the bare summary, without its evidence.
- **Nothing in the app called `POST /api/worries/{id}/outcome`**, so "did it happen?" was never asked.

**Built (`app`):**
- Home leads with **one "Act now" card per alert**: summary, worry, source, when, and up to 3 evidence values.
- The detail screen shows the alert with an evidence table and **Done, close it**.
- Closing a worry whose watcher was approved asks once: **"Did what you feared happen?"** Yes or No → `/outcome` → Home.
- Evidence is watched content, rendered as escaped text only.

**Proof, without touching your Warden:** a separate **TEST-alerts Warden** ran on `127.0.0.1:8020` with its own DB and key, the real compiler and the real OpenShell driver.
- The test worry: "TEST of the alert path, not a real worry: tell me to act now if … current temperature in Berlin is above -40 degrees."
- Pipeline: triage → codegen → dry run in a `cwd-*` sandbox → card `GET api.open-meteo.com/v1/forecast` (19 s). **I approved this test card on the TEST Warden only.**
- 10 s after approval, sandbox `cw-jeapx1nv` reported `act_now`, "Current temperature in Berlin is 14.0°C, above -40°C.", with evidence `{"temperature_c": 14.0}`. **Exactly one `act_now` event.**
- In the app (390×844, Playwright against the TEST Warden): Home showed 1 alert card → the detail showed the evidence → Done, close it → "Did what you feared happen?" → Yes → back on Home, "All quiet.". `fear_came_true=true` was stored. **Console errors: none.**
- Screenshots: `~/custody-evidence/alert-path/*.png` (outside the repo).

**Removed afterwards:**
- Let-go retired the watcher and deleted its sandbox: `openshell sandbox list` = custody-brain, cw-76epww8s, cw-gnnrrs3z, cw-zzrsdcze (yours).
- The TEST Warden and its Vite server were stopped, and its data dir deleted.
- Your `/api/ledger` is unchanged.

**Seen on the way, fixed in block 9:** the fear line lowercased the first letter ("The fear: open-Meteo…", the same bug as "s-Bahn").

### 12. Demo check (everything that doesn't need your phone)
| # | Check | Result | Evidence |
|---|---|---|---|
| 1 | `/api/health` healthy; sandbox count = active watchers | ✅ | `{"status":"ok","sandboxes_live":3}`, 3 watching worries, `demo-evidence.sh` §1 "3 running watchers, 3 watcher sandboxes, all Ready, no strays" |
| 2 | Hand-over → card → approve → watching in < 60 s | ◐ | Live pipeline on the test Warden: hand-over → card in **19 s**, approve → watching at once. `make e2e` (real Warden, recorded answers) passes. **The phone part needs you** |
| 3 | A watcher produced `act_now` in **real usage**, and the alert card shows evidence | ❌ (real) / ✅ (test) | None of your worries has hit `act_now` (no `act_now` event in any timeline). The card with evidence is proven on the test Warden (block 7, screenshots) |
| 4 | An unusual worry (not parcel or weather) compiles and passes its dry run | ✅ | GitHub status (`http_json`, `www.githubstatus.com/api/v2/status.json`) and the school calendar (`ics_calendar`, Google ICS) both passed their dry runs and are watching in sandboxes `cw-zzrsdcze` / `cw-76epww8s` |
| 5 | "Is Anna OK?" from the 2nd machine < 10 s; receipt; 2nd machine's OpenShell egress log shows only relay traffic | ◐ | Two Wardens on this host: **0.88 s**, receipt 316 bytes (block 5). The Mac isn't done (you). **The last clause can't be met as written:** no OpenShell runs on the Mac. `anna-setup.sh proof` lists the Warden process's TCP connections instead (rehearsed: relay 100.81.50.38:443 + loopback only) |
| 6 | Ledger = `/api/ledger`; nothing fake presented as real | ✅ | All tiles equal the API (read-only tour + `make e2e` ledger spec); the unmeasured tiles say so; 91.4% is labelled research |
| 7 | Installed to home screen; dark and light; no console errors | ◐ | Dark + light on 16 screens, **0 console errors** (desktop Chromium, 390×844). Icons and manifest fixed and served. **The iPhone install needs you** |
| 8 | README states the hosted-inference limit (ADR-0003) | ✅ | README "Honest limits": worry text goes to NVIDIA's hosted endpoints, and L1 doesn't keep it on-device |
| 9 | `restart.sh` tested since the last deploy | ✅ | Run after every deploy today, last at 09:48: `HEALTHY in 32s` |
| 10 | DESIGN §8 matches the system | ◐ | Mismatches below |

**DESIGN §8 (video script) vs what the system really does:**
1. **Hook "91% of worries never come true."** That is a research result (LaFreniere & Newman 2019, people with generalized anxiety), not Custody data and not all worries. Say "In one study, 91% …". The app labels it the same way.
2. **Parcel scene.** The DHL adapter needs `DHL_API_KEY` and has never run live. Use a worry that is really being watched: rain 16:00–19:00 (`cw-gnnrrs3z`), GitHub (`cw-zzrsdcze`) or the school calendar. "Silence" is true: `ok` results are silent.
3. **"Will the strike hit my U8 tomorrow?"**
   - `transit_bvg` reads a stop's departures (cancellations and delays). It can't know about a strike in advance.
   - The worry must name a stop ("U8 from Hermannplatz"); otherwise it parks and asks for one.
   - It now watches only the direction of travel and ≥ 10 min, and BVG's API was down this morning.
   - Use GitHub status or the school calendar as the unusual worry, or a transit worry that names a stop and a time.
4. **"Is Anna OK?" → "Normal day."** True only after Anna taps **I'm OK** on the Mac, or has 3+ days of activity history. "The audit log: one tiny encrypted message, zero locations": show the privacy receipt in the app, and `demo-evidence.sh` §5 (relay rows). The Mac side has no OpenShell log.
5. **Stats wall, "real numbers from the week".** They're real but small: 5 handed over, 3 watched, 0 outcomes. **No came-true number and no 91.4% bar appear until an outcome is recorded.** The rain worry closes at 19:00 and the GitHub one at 23:59, both after the 18:00 recording.
6. **Alerts.** There is no web push (cut); the alert is an in-app card. No real `act_now` has happened yet (see item 3 above).
7. **Architecture and vision**: match. L3 is presented as vision, and it is not built.

### 11. README (T-21)
- `README.md` contains:
  - the pitch (91.4% framed as research);
  - one Mermaid architecture diagram;
  - a **quickstart verified from a fresh clone of GitHub `main`**;
  - a real / simulated / not measured / cut table;
  - the ADR-0003 hosted-inference limit and the other honest limits;
  - a security model summary;
  - a "For the judges" section mapped to the three criteria.
- **Fresh-clone test:** `make setup` (4 s, warm cache), then `make dev WARDEN_PORT=8031 APP_PORT=5181`. The app gave 200 and `/api/health` gave 200 through the app's proxy. A DHL worry handed over on recorded answers reached `awaiting_approval` with its card.
- **Found and fixed on the way:**
  - Without `.env` the dev Warden had no device token, so every call was a 401 and the quickstart couldn't work. `make dev` now creates `.env` and writes a random token into it (never printed).
  - The dev Warden now binds 127.0.0.1, and the ports can be set.

### 10. `scripts/demo-evidence.sh` (for the screen recording)
Run on the host: `./scripts/demo-evidence.sh` (about 25 s; prints no token, key or body). Live output at 09:45 Berlin, all ✔:
1. **Sandboxes:** `cw-76epww8s` / `cw-gnnrrs3z` / `cw-zzrsdcze` Ready, one per watching worry (school, rain, GitHub), plus `custody-brain`. "3 running watchers, 3 watcher sandboxes, all Ready, no strays".
2. **Generated policy** of the rain watcher: one `GET api.open-meteo.com/v1/forecast` rule, `/usr/local/bin/python3.12` only, Landlock strict.
3. **Denial:** a throwaway `cwd-proof-*` sandbox with the *same* policy asks for example.com → `ProxyError`, and OpenShell's own log shows: `NET:OPEN [MED] DENIED /usr/local/bin/python3.12(34) -> example.com:443 [policy:- engine:opa] [reason:endpoint example.com:443 is not allowed by any policy]`. The probe sandbox is deleted after, and real watchers are untouched.
4. **Brain:** `custody-brain` Ready, nemotron-3-super-120b-a12b, inference healthy, OpenShell 0.0.116.
5. **Relay:** 6 rows (from the block 5 test, which expire at ~07:08 UTC on 3 Oct): key ids, sizes and 6.5–7.1 bits/byte; no vocabulary word or JSON field name. **For the video, ask "Is Anna OK?" first, so the rows are fresh.**

Every OpenShell call goes through the driver (AGENTS #3). The driver gained a read-only `list_sandboxes()` (tested with the fake CLI).

### 9. App polish (phone first)
- **Status bar:**
  - With `black-translucent` the page runs under the clock. `pt-[max(env(safe-area-inset-top),1.5rem)]` only protected the first screen, so scrolled content slid under the status bar.
  - Now a fixed `body::before` strip, `env(safe-area-inset-top)` high and in the page colour, sits on top (z 50, no pointer events), and `html`/`body` are painted with the theme.
  - **I can't emulate the iPhone notch here, so check it on the phone.**
- **Home screen:**
  - `apple-touch-icon` was an SVG, which iOS ignores (it then uses a screenshot), and the manifest had only an SVG icon.
  - Now there are PNGs: 180 (apple-touch-icon), 192, 512 and maskable 512. They show the app's orb on `#161412`.
  - The manifest gains `id` and `scope`, and `mobile-web-app-capable` was added. `display: standalone` plus `apple-mobile-web-app-capable` gives full screen with no browser bar.
  - All are served (200) through the tailnet URL. **Delete the old home-screen icon and add it again**: iOS caches the icon.
- **"s-Bahn":** the detail screen lowercased the fear's first letter (`charAt(0).toLowerCase()`). The model's text was "S-Bahn …". It's now shown as written (`fearLine`), with a test.
- **Dark + light:** a read-only tour of all 16 screens (home, people, sharing, ledger, both pairing screens, every one of your worries) at 390×844 against your real Warden. **No console errors or warnings.**
- **Wording read-through:**
  - Fixed: "your calendar" for a public calendar → "a calendar"; an internal adapter name shown as a source (`weather_openmeteo`) → "Open-Meteo forecast"; the ledger fixes in block 8; the alert and outcome UI in block 7.
  - Left as data, from the model, historical: "The fear: … user does not notice", the night S7's "09:00 UTC", and the old "stop search didn't answer" lines on the 08:16 worries.
  - **Two rows on Home mislead:** under "For worry time", the night's S7 build failure shows as "Parked", and the T-11 Lena test worry is there too. They're your rows, so I didn't touch their status: **Let it go on both** (Needs Myron).

### 8. Ledger truth: your real numbers (07:34 UTC)
`GET /api/ledger` = `{"worries_total":5,"active":3,"never_needed_you":0,"needed_you":0,"median_warning_lead_h":0.0,"came_true_rate":0.0,"came_true_by_type":{},"watchers_built":4,"sandboxes_live":3,"endpoints_denied":0,"peer_questions_answered":0,"locations_shared":0}`

| Worry | Status | Counted? |
|---|---|---|
| School moves Friday's parents' evening | watching | ✅ |
| S7 disrupted ~9:00 (the second attempt, denied 06:15 → let go) | resolved, no outcome | ✅ |
| Rain in Berlin 16:00–19:00 | watching | ✅ |
| GitHub down this evening | watching | ✅ |
| "What if I don't win the challenge?" | parked | ✅ |
| S7 first attempt (night) | parked | ✗ build failure |
| S7 ×2 at 08:16 / 08:18 (BVG down) | resolved | ✗ build failure |
| "Lena … T-11 test dinner" | parked | ✗ **test** (marked today) |

- **5 handed over, 3 watched, 0 outcomes known** (so no came-true claim), and 0 questions about you.
- **4 watchers built**: school, rain, GitHub, and the denied S7 card. Per CONTRACTS, "built" means "passed its dry run", so it doesn't mean "ran". **3 sandboxes live**: `cw-76epww8s`, `cw-gnnrrs3z`, `cw-zzrsdcze`.
- No test peers: TEST-Anna was removed and the people list is empty. The TEST-alerts Warden had its own DB, so it never touched these numbers.
- **What changed:**
  - `test` is a timeline kind now (CONTRACTS §1/§5), and the ledger skips test worries and their watchers.
  - `scripts/mark_test_worry.py` is append-only and backs up first (`warden.db.bak-20261002-073333-mark-test`). It appended one event to the Lena worry; nothing else changed. `worries_total` went 6 → 5.
- **Ledger screen vs API:** every tile equals the API (`make e2e` checks it field by field), except where the screen now deliberately says less:
  - **Endpoints denied** shows "—" and says it isn't wired to the sandbox log yet. It showed a real-looking `0`, while the API returns a constant.
  - "warned a median 0 min ahead" can no longer appear (the median isn't measured).
  - The 91.4% bar reads **"Research, not your data: Penn State study"**, and the footnote cites LaFreniere & Newman 2019. It only shows once you have outcomes.
  - The README hero and the video hook use 91.4%/91% as research with the citation (checked in block 11).

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
