#!/usr/bin/env bash
# T-11: wire the brain (OpenClaw in the NemoClaw sandbox) to Custody. Idempotent; never prints
# a secret.
#   1. the `custody` skill            -> nemoclaw <brain> skill install brain/skills/custody
#   2. the standing orders            -> a marked block in the workspace AGENTS.md (always loaded)
#   3. the Warden's MCP tools         -> nemoclaw <brain> mcp add custody --url https://<tailnet>/mcp/
# Step 3 needs Tailscale Serve (HTTPS on the tailnet name): NemoClaw only registers HTTPS MCP
# servers, and the sandbox can't reach host loopback. The tailnet name resolves to a CGNAT
# address, so it is admitted with --trusted-private-host (exact host, pinned in the policy).
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
BRAIN="${CUSTODY_BRAIN_SANDBOX:-custody-brain}"
CONF="$HOME/.config/custody"
WORKSPACE=/sandbox/.openclaw/workspace
umask 077

echo "== 1. custody skill"
nemoclaw "$BRAIN" skill install brain/skills/custody | tail -2

echo "== 2. standing orders -> $WORKSPACE/AGENTS.md"
# `upload` treats the destination as a directory.
nemoclaw "$BRAIN" exec -- rm -rf /tmp/custody-orders /tmp/custody-standing-orders.md >/dev/null
nemoclaw "$BRAIN" upload brain/standing-orders.md /tmp/custody-orders >/dev/null
nemoclaw "$BRAIN" exec -- sh -ec '
  f='"$WORKSPACE"'/AGENTS.md; new=/tmp/custody-orders/standing-orders.md
  test -s "$new"; touch "$f"
  sed -i "/CUSTODY-STANDING-ORDERS:BEGIN/,/CUSTODY-STANDING-ORDERS:END/d" "$f"
  printf "\n" >> "$f"; cat "$new" >> "$f"; rm -rf /tmp/custody-orders
  grep -c "CUSTODY-STANDING-ORDERS" "$f"' | tail -1 | sed 's/^/marker lines in AGENTS.md (want 2): /'

echo "== 3. MCP: Warden /mcp/ -> brain"
host=$(tailscale status --json | python3 -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))')
changed=0
if ! grep -q '^WARDEN_MCP_TOKEN=.' "$CONF/warden.env"; then
  printf 'WARDEN_MCP_TOKEN=%s\n' "$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')" >> "$CONF/warden.env"
  changed=1
fi
if ! grep -q "^WARDEN_MCP_ALLOWED_HOSTS=$host," "$CONF/warden.env"; then
  sed -i '/^WARDEN_MCP_ALLOWED_HOSTS=/d' "$CONF/warden.env"
  printf 'WARDEN_MCP_ALLOWED_HOSTS=%s,%s:*\n' "$host" "$host" >> "$CONF/warden.env"
  changed=1
fi
[ $changed -eq 0 ] || { systemctl --user restart custody-warden; sleep 3; echo "warden restarted with MCP settings"; }

if ! out=$(timeout 20 sudo tailscale serve --bg --https=443 --set-path /mcp http://127.0.0.1:8000/mcp 2>&1); then
  echo "BLOCKED: Tailscale Serve is not enabled for this tailnet. Approve it, then re-run:"
  printf '%s\n' "$out" | grep -o 'https://login.tailscale.com[^ ]*' | head -1
  exit 2
fi
# ufw drops the brain container's packets to the tailnet IP unless allowed: one narrow rule.
scripts/ufw-brain-mcp.sh
# The token goes to OpenShell's provider store; the sandbox only ever sees a placeholder.
CUSTODY_MCP_TOKEN=$(sed -n 's/^WARDEN_MCP_TOKEN=//p' "$CONF/warden.env") \
  nemoclaw "$BRAIN" mcp add custody --url "https://$host/mcp/" --env CUSTODY_MCP_TOKEN \
    --trusted-private-host "$host" | tail -5
nemoclaw "$BRAIN" mcp status custody --json | python3 -c '
import json, sys
d = json.load(sys.stdin)
print("trustedPrivateTarget:", (d.get("trustedPrivateTarget") or {}).get("state"))'
