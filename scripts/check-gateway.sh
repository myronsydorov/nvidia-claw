#!/usr/bin/env bash
# T-02 check: the OpenClaw gateway's OpenAI-compatible endpoint answers on loopback with the
# token, refuses without it, and is NOT reachable on any other address (AGENTS invariant #4).
# The token comes from CUSTODY_GATEWAY_ENV (default ~/.config/custody/gateway.env, mode 0600,
# outside git) and is never printed.
set -euo pipefail

ENV_FILE="${CUSTODY_GATEWAY_ENV:-$HOME/.config/custody/gateway.env}"
[ -r "$ENV_FILE" ] || { echo "FAIL: $ENV_FILE missing (see HANDOFF.md, task B)"; exit 1; }
set -a; . "$ENV_FILE"; set +a
URL="${OPENCLAW_GATEWAY_URL:-http://127.0.0.1:18789}"
PORT="${URL##*:}"
fail=0

case "$URL" in
  http://127.0.0.1:*|http://localhost:*) ;;
  *) echo "FAIL: OPENCLAW_GATEWAY_URL is not loopback"; fail=1 ;;
esac

body=$(curl -s -m 180 "$URL/v1/chat/completions" \
  -H "Authorization: Bearer $OPENCLAW_GATEWAY_TOKEN" -H 'content-type: application/json' \
  -d '{"model":"openclaw","messages":[{"role":"user","content":"Reply with exactly: pong"}]}' || true)
if printf '%s' "$body" | grep -q '"object":"chat.completion"'; then
  echo "ok: loopback completion: $(printf '%s' "$body" | grep -o '"content":"[^"]*"' | head -1)"
else
  echo "FAIL: no completion from $URL"; fail=1
fi

code=$(curl -s -m 10 -o /dev/null -w '%{http_code}' "$URL/v1/chat/completions" \
  -H 'content-type: application/json' -d '{}' || true)
[ "$code" = 401 ] && echo "ok: no token -> 401" || { echo "FAIL: no token -> $code"; fail=1; }

if ss -ltnH "( sport = :$PORT )" | awk '{print $4}' | grep -vqE '^(127\.0\.0\.1|\[::1\]):'; then
  echo "FAIL: something listens on :$PORT beyond loopback"; ss -ltn "( sport = :$PORT )"; fail=1
else
  echo "ok: :$PORT listens on loopback only"
fi

for ip in $(ip -4 -o addr show scope global | awk '{print $4}' | cut -d/ -f1); do
  if curl -s -m 5 -o /dev/null "http://$ip:$PORT/"; then
    echo "FAIL: reachable on $ip:$PORT"; fail=1
  else
    echo "ok: refused on $ip:$PORT"
  fi
done
exit $fail
