# Handoff: production host bring-up (2026-10-01)

Host: DigitalOcean `ubuntu-s-4vcpu-8gb-fra1`, Ubuntu 24.04, user `myron`, ufw on, Tailscale up (`100.81.50.38`).
NemoClaw v0.0.124 · OpenShell 0.0.116 · OpenClaw v2026.7.1 · brain sandbox `custody-brain`.

## Status
| Task | State |
|---|---|
| A. NemoClaw healthy | done |
| B. T-02 gateway chat endpoint (loopback) | todo |
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

## Decisions made

## Blocked

## Owner: do this next
