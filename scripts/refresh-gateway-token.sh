#!/usr/bin/env bash
# Re-read the brain's OpenClaw gateway token into ~/.config/custody/gateway.env (0600, outside
# git). The token rotates whenever the brain sandbox restarts, so restart.sh runs this before
# restarting the Warden. Never prints the token.
set -euo pipefail
export PATH="$HOME/.local/bin:$PATH"
BRAIN="${CUSTODY_BRAIN_SANDBOX:-custody-brain}"
FILE="$HOME/.config/custody/gateway.env"
umask 077
mkdir -p "$(dirname "$FILE")"
token=$(nemoclaw "$BRAIN" gateway-token --quiet 2>/dev/null | tail -1)
[ -n "$token" ] || { echo "could not read the gateway token for $BRAIN"; exit 1; }
tmp=$(mktemp "$FILE.XXXXXX")
printf 'OPENCLAW_GATEWAY_URL=http://127.0.0.1:18789\nOPENCLAW_GATEWAY_TOKEN=%s\n' "$token" > "$tmp"
unset token
mv "$tmp" "$FILE"
echo "gateway token refreshed in $FILE"
