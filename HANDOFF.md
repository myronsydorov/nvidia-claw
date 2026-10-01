# Handoff: production host bring-up (2026-10-01)

Host: DigitalOcean `ubuntu-s-4vcpu-8gb-fra1`, Ubuntu 24.04, user `myron`, ufw on, Tailscale up (`100.81.50.38`).
NemoClaw v0.0.124 · OpenShell 0.0.116 · OpenClaw v2026.7.1 · brain sandbox `custody-brain`.

## Status
| Task | State |
|---|---|
| A. NemoClaw healthy | done |
| B. T-02 gateway chat endpoint (loopback) | done |
| C. T-04 OpenShell SandboxDriver | done (security-reviewed, hardened) |
| D. Deploy (systemd + tailscale serve, T-20 restart.sh) | services + restart.sh done; **tailnet URL blocked on the owner** (enable Tailscale Serve) |
| E. T-11 brain | built and installed; **MCP hookup blocked on the same Tailscale Serve approval** |

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
