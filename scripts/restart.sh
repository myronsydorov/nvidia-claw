#!/usr/bin/env bash
# T-20: bring Custody back after a reboot (or any outage), then prove it is healthy.
# Target: healthy within 5 minutes. Safe to run any time; it never prints a secret.
#
#   docker -> NemoClaw's OpenShell gateway (user service) -> the brain sandbox + its loopback
#   forward -> custody-relay / custody-app / custody-warden. The Warden itself restarts stopped
#   watcher sandboxes (or recreates missing ones from the approved policy) when it starts, so
#   this script never touches watcher sandboxes (AGENTS invariant #3).
set -uo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
BRAIN="${CUSTODY_BRAIN_SANDBOX:-custody-brain}"
BUDGET_S=300
start=$SECONDS
failures=0

say() { printf '[%3ds] %s\n' $((SECONDS - start)) "$*"; }
wait_for() {  # wait_for <seconds> <description> <command...>
  local limit=$1 what=$2; shift 2
  local until=$((SECONDS + limit))
  while ! "$@" >/dev/null 2>&1; do
    if [ $SECONDS -ge $until ]; then say "FAIL: $what"; failures=$((failures + 1)); return 1; fi
    sleep 2
  done
  say "ok: $what"
}
brain_ready() { nemoclaw "$BRAIN" status 2>/dev/null | grep -qE 'Phase:.*Ready'; }
gateway_answers() {  # the OpenClaw gateway on loopback refuses us without the token: it's up
  [ "$(curl -s -m 5 -o /dev/null -w '%{http_code}' http://127.0.0.1:18789/v1/chat/completions \
        -H 'content-type: application/json' -d '{}')" = 401 ]
}
warden_ok() {
  curl -sf -m 5 -H "Authorization: Bearer $WARDEN_DEVICE_TOKEN" http://127.0.0.1:8000/api/health \
    | grep -q '"status":"ok"'
}

say "== docker"
systemctl is-active --quiet docker || sudo systemctl start docker
wait_for 60 "docker daemon" docker info

say "== OpenShell gateway (nemoclaw-openshell-gateway.service)"
systemctl --user start nemoclaw-openshell-gateway
wait_for 90 "OpenShell gateway connected" sh -c 'openshell status 2>/dev/null | grep -q Connected'

say "== brain sandbox '$BRAIN'"
brain_ready || nemoclaw "$BRAIN" start >/dev/null 2>&1 || true
wait_for 120 "brain sandbox Ready" brain_ready
if ! gateway_answers; then
  say "brain gateway/forward not answering: nemoclaw $BRAIN recover"
  nemoclaw "$BRAIN" recover >/dev/null 2>&1 || true
fi
wait_for 90 "OpenClaw gateway on 127.0.0.1:18789" gateway_answers
# The gateway token rotates when the brain sandbox restarts; the Warden reads the new one.
scripts/refresh-gateway-token.sh | sed 's/^/    /' || failures=$((failures + 1))

say "== custody services"
systemctl --user restart custody-relay custody-app custody-warden
set -a; . "$HOME/.config/custody/warden.env"; set +a
wait_for 30 "relay /v1/health" curl -sf -m 5 http://127.0.0.1:8100/v1/health
wait_for 30 "app on 127.0.0.1:8300" curl -sf -m 5 -o /dev/null http://127.0.0.1:8300/
wait_for 60 "warden /api/health" warden_ok

say "== checks"
scripts/check-gateway.sh | sed 's/^/    /' || failures=$((failures + 1))
health=$(curl -s -m 5 -H "Authorization: Bearer $WARDEN_DEVICE_TOKEN" http://127.0.0.1:8000/api/health)
say "warden: $health"
# Watcher sandboxes are reconciled by the Warden as it starts; give it a moment, then list.
sleep 5
openshell sandbox list 2>/dev/null | sed 's/\x1b\[[0-9;]*m//g; s/^/    /'
if sudo -n true 2>/dev/null; then
  serve=$(timeout 10 sudo tailscale serve status 2>&1 | head -6)
  say "tailscale serve:"; printf '%s\n' "$serve" | sed 's/^/    /'
fi

elapsed=$((SECONDS - start))
if [ $failures -eq 0 ] && [ $elapsed -le $BUDGET_S ]; then
  say "HEALTHY in ${elapsed}s (budget ${BUDGET_S}s)"
else
  say "NOT HEALTHY: $failures failure(s), ${elapsed}s"
  exit 1
fi
