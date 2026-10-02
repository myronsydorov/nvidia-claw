#!/usr/bin/env bash
# Anna's Warden + app on a Mac, paired with Myron's Warden through the server's relay (tailnet).
# Runs under macOS's bash 3.2 (call it from zsh as shown in docs/ANNA_SETUP.md).
#
#   scripts/anna-setup.sh          install what's missing, write ~/.config/custody-anna/warden.env once
#   scripts/anna-setup.sh start    start the Warden (background) and the app (foreground; Ctrl-C stops both)
#   scripts/anna-setup.sh token    copy the device token to the clipboard again
#   scripts/anna-setup.sh proof    every network connection Anna's Warden has, and what it answered
#   scripts/anna-setup.sh stop     stop the Warden if `start` was killed hard
#
# Anna's Warden only *answers* "Is Anna OK?". It builds no watchers (compiler and scheduler off),
# so nothing runs in a sandbox here and no worry text leaves this Mac. It never prints a secret.
set -euo pipefail
cd "$(dirname "$0")/.."

RELAY_URL="${ANNA_RELAY_URL:-https://ubuntu-s-4vcpu-8gb-fra1.tail081ca8.ts.net/relay}"
PORT="${ANNA_PORT:-8000}"
APP_PORT="${ANNA_APP_PORT:-5173}"
CONF="$HOME/.config/custody-anna"
DATA="$HOME/.local/share/custody-anna"
ENV_FILE="$CONF/warden.env"
PNPM_VERSION=9.15.9
export PNPM_HOME="${PNPM_HOME:-$HOME/Library/pnpm}"
export PATH="$HOME/.local/bin:$PNPM_HOME:$PATH"

say() { printf '\n== %s\n' "$*"; }
die() { printf '\nSTOP: %s\n' "$*" >&2; exit 1; }
token() { grep '^WARDEN_DEVICE_TOKEN=' "$ENV_FILE" | cut -d= -f2-; }
warden_pid() { cat "$DATA/warden.pid" 2>/dev/null || true; }
healthy() {
  curl -sf -m 3 -H "Authorization: Bearer $(token)" "http://127.0.0.1:$PORT/api/health" >/dev/null
}
copy_token() {
  if command -v pbcopy >/dev/null 2>&1; then
    token | tr -d '\n' | pbcopy
    echo "The device token is on your clipboard (Cmd-V into the app)."
  else
    echo "No pbcopy here; the device token is the WARDEN_DEVICE_TOKEN line in $ENV_FILE."
  fi
}

setup() {
  [ "$(uname)" = Darwin ] || echo "note: not macOS ($(uname)); continuing anyway"
  say "tools"
  command -v git >/dev/null || die "git is missing: run  xcode-select --install  and try again"
  if ! command -v uv >/dev/null; then
    echo "installing uv (Python package manager) into ~/.local/bin"
    curl -LsSf https://astral.sh/uv/install.sh | sh
  fi
  if ! command -v pnpm >/dev/null; then
    echo "installing pnpm $PNPM_VERSION into $PNPM_HOME"
    curl -fsSL https://get.pnpm.io/install.sh | env PNPM_VERSION="$PNPM_VERSION" SHELL=/bin/zsh sh -
  fi
  if ! command -v node >/dev/null || [ "$(node -p 'process.versions.node.split(".")[0]')" -lt 20 ]; then
    echo "installing Node 22 through pnpm"
    pnpm env use --global 22
  fi
  echo "uv $(uv --version | cut -d' ' -f2) · pnpm $(pnpm --version) · node $(node --version)"

  say "relay (on the tailnet)"
  if curl -sf -m 10 "$RELAY_URL/v1/health" >/dev/null; then
    echo "ok: $RELAY_URL/v1/health"
  else
    die "can't reach $RELAY_URL. Is Tailscale running on this Mac and logged in to the same tailnet?"
  fi

  say "dependencies (a few minutes the first time)"
  uv sync --all-packages --frozen -q
  pnpm -C app install --frozen-lockfile --silent --config.confirmModulesPurge=false

  say "Anna's Warden settings"
  umask 077
  mkdir -p "$CONF" "$DATA"
  if [ -f "$ENV_FILE" ]; then
    echo "kept $ENV_FILE (delete it to start over with a new identity)"
  else
    cat > "$ENV_FILE" <<EOF
# Anna's Warden: answers reassurance questions only. Written by scripts/anna-setup.sh.
CUSTODY_SANDBOX=mock
WARDEN_COMPILER=off
WARDEN_SCHEDULER=off
RELAY_URL=$RELAY_URL
WARDEN_DB_PATH=$DATA/warden.db
WARDEN_KEY_PATH=$DATA/warden.key
WARDEN_STOP_CACHE=$DATA/bvg_stops.json
WARDEN_DEVICE_TOKEN=$(openssl rand -hex 32)
EOF
    echo "created $ENV_FILE (mode 600, device token inside)"
  fi
  chmod 600 "$ENV_FILE"
  say "done. Next:  ./scripts/anna-setup.sh start"
}

start() {
  [ -f "$ENV_FILE" ] || die "run  ./scripts/anna-setup.sh  first"
  if lsof -nP -iTCP:"$PORT" -sTCP:LISTEN >/dev/null 2>&1; then
    die "port $PORT is busy (another Warden?). Run  ./scripts/anna-setup.sh stop  or set ANNA_PORT"
  fi
  umask 077
  mkdir -p "$DATA"
  say "Anna's Warden on 127.0.0.1:$PORT (log: $DATA/warden.log)"
  (
    set -a
    . "$ENV_FILE"
    set +a
    exec .venv/bin/uvicorn warden.app:app --host 127.0.0.1 --port "$PORT" --no-access-log
  ) >>"$DATA/warden.log" 2>&1 &
  echo $! > "$DATA/warden.pid"
  trap 'stop_warden' EXIT INT TERM
  i=0
  until healthy; do
    i=$((i + 1))
    [ $i -lt 60 ] || die "the Warden didn't start; see $DATA/warden.log"
    sleep 0.5
  done
  echo "ok: /api/health"
  copy_token
  say "the app: open http://127.0.0.1:$APP_PORT and paste the token (Ctrl-C here stops both)"
  open_flag=""
  [ "$(uname)" = Darwin ] && open_flag="--open"
  WARDEN_URL="http://127.0.0.1:$PORT" pnpm -C app exec vite --host 127.0.0.1 --port "$APP_PORT" \
    --strictPort $open_flag
}

stop_warden() {
  pid=$(warden_pid)
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    kill "$pid" && echo "stopped Anna's Warden (pid $pid)"
  fi
  rm -f "$DATA/warden.pid"
}

proof() {
  [ -f "$ENV_FILE" ] || die "run  ./scripts/anna-setup.sh  first"
  pid=$(warden_pid)
  [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null || die "Anna's Warden isn't running (./scripts/anna-setup.sh start)"
  relay_host=$(printf '%s' "$RELAY_URL" | sed -E 's#^https?://([^/:]+).*#\1#')
  relay_ip=$(python3 -c "import socket,sys; print(socket.gethostbyname(sys.argv[1]))" "$relay_host" 2>/dev/null || echo "?")
  say "every TCP connection of Anna's Warden right now (pid $pid)"
  echo "expected: the relay $relay_host ($relay_ip):443, and loopback (the app on this Mac)"
  lsof -nP -a -p "$pid" -iTCP 2>/dev/null | awk 'NR == 1 || /ESTABLISHED|LISTEN|SYN_SENT/' || true
  others=$(lsof -nP -a -p "$pid" -iTCP -sTCP:ESTABLISHED 2>/dev/null | awk 'NR > 1 {print $9}' \
    | sed -E 's/.*->//' | grep -v "^127\.0\.0\.1:" | grep -v "^$relay_ip:443$" || true)
  if [ -z "$others" ]; then
    echo "RESULT: no connection to anything but the relay and loopback."
  else
    echo "RESULT: unexpected peers:"; echo "$others"
  fi
  say "what an allowed person asking 'Are you OK?' would get now"
  curl -s -H "Authorization: Bearer $(token)" "http://127.0.0.1:$PORT/api/me/signal"; echo
  say "every question asked about Anna (newest first), and what was answered"
  curl -s -H "Authorization: Bearer $(token)" "http://127.0.0.1:$PORT/api/sharing-rules" \
    | python3 -c 'import json,sys
for e in json.load(sys.stdin)["questions_log"]:
    print(e["asked_at"][:19], e["question"], "->", e["answer_level"])'
  cat <<'EOF'

What this does and doesn't prove, honestly:
- No OpenShell sandbox runs on this Mac: Anna's Warden runs no watchers, so there is nothing
  to sandbox. Privacy here rests on the Warden's code, not on a jail:
  1. an answer is one of a fixed set of words, checked before it is encrypted (tests:
     warden/tests/test_reassurance_vocabulary.py), and it never includes location;
  2. it travels end-to-end encrypted; the relay stores ciphertext only (dump it on the
     server: scripts/demo-evidence.sh);
  3. the list above is every TCP connection this Warden process has open right now.
EOF
}

case "${1:-setup}" in
  setup) setup ;;
  start) start ;;
  token) [ -f "$ENV_FILE" ] || die "run setup first"; copy_token ;;
  proof) proof ;;
  stop) stop_warden ;;
  *) die "usage: scripts/anna-setup.sh [setup|start|token|proof|stop]" ;;
esac
