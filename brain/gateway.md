# OpenClaw gateway: loopback chat endpoint (T-02)

The brain runs in the NemoClaw sandbox `custody-brain`. Its OpenClaw gateway listens inside the
sandbox on 18789 and OpenShell forwards it to **`127.0.0.1:18789` on the host only** (AGENTS #4).

Enable the OpenAI-compatible endpoint (one config key, then restart):
```bash
nemoclaw custody-brain exec -- openclaw config set gateway.http.endpoints.chatCompletions.enabled true
nemoclaw custody-brain gateway restart
```

The token lives outside git in `~/.config/custody/gateway.env` (mode 0600), written without
echoing it:
```bash
umask 077; mkdir -p ~/.config/custody
t=$(nemoclaw custody-brain gateway-token --quiet | tail -1)
printf 'OPENCLAW_GATEWAY_URL=http://127.0.0.1:18789\nOPENCLAW_GATEWAY_TOKEN=%s\n' "$t" > ~/.config/custody/gateway.env
unset t
```
Only the Warden reads it (systemd `EnvironmentFile=`). `scripts/check-gateway.sh` proves a loopback
completion, a 401 without the token, and that every non-loopback address refuses the port.
