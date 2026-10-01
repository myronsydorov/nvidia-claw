# Handoff: production host bring-up (2026-10-01)

Host: DigitalOcean `ubuntu-s-4vcpu-8gb-fra1`, Ubuntu 24.04, user `myron`, ufw on, Tailscale up (`100.81.50.38`).
NemoClaw v0.0.124 · OpenShell 0.0.116 · OpenClaw v2026.7.1 · brain sandbox `custody-brain`.

## Status
| Task | State |
|---|---|
| A. NemoClaw healthy | done |
| B. T-02 gateway chat endpoint (loopback) | done |
| C. T-04 OpenShell SandboxDriver | todo |
| D. Deploy (systemd + tailscale serve, T-20 restart.sh) | todo |
| E. T-11 brain | todo |

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

## Decisions made
- I did not read the brain's `openclaw.json` (it holds secrets; the read was refused by the permission guard). I changed only the one key via `openclaw config set`.
- Fixed a flaky app test (`events.test.ts` used a fixed 5 ms sleep; now polls up to 1 s). Baseline after: 458 Python + 83 app tests pass.
- Installed on the host: `uv` (~/.local/bin), `pnpm@9` (npm -g), `make`, `xprintidle`.
- Git identity for this repo set to match history (`Myron Sydorov <bymyronsydorov@gmail.com>`); the very first handoff commit used `sydorov.myron@gmail.com`.

## Blocked

## Owner: do this next
