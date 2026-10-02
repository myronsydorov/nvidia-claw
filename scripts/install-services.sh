#!/usr/bin/env bash
# Install Custody on a NemoClaw host as systemd *user* services (like NemoClaw's own
# nemoclaw-openshell-gateway.service), served to the tailnet only via `tailscale serve`.
# Idempotent: re-run after pulling. Never prints a secret.
#
#   custody-relay   127.0.0.1:8100  ciphertext mailbox
#   custody-warden  127.0.0.1:8000  /api (CUSTODY_SANDBOX=openshell)
#   custody-app     127.0.0.1:8300  the built PWA
#   tailscale serve https://<host>.<tailnet>.ts.net/  -> app, /api -> warden   (no Funnel)
set -euo pipefail
cd "$(dirname "$0")/.."
REPO=$(pwd)
export PATH="$HOME/.local/bin:$PATH"
CONF="$HOME/.config/custody"
DATA="$HOME/.local/share/custody"
umask 077
mkdir -p "$CONF" "$DATA" "$HOME/.config/systemd/user"

[ -r "$CONF/gateway.env" ] || { echo "missing $CONF/gateway.env: see brain/gateway.md (T-02)"; exit 1; }

# This host's Warden settings. Later EnvironmentFiles override .env, so this wins.
if [ ! -f "$CONF/warden.env" ]; then
  token=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
  cat > "$CONF/warden.env" <<EOF
CUSTODY_SANDBOX=openshell
CUSTODY_LLM_REPLAY=
CUSTODY_WATCHER_IMAGE=custody-watcher:latest
OPENSHELL_BIN=$HOME/.local/bin/openshell
RELAY_URL=http://127.0.0.1:8100
WARDEN_DB_PATH=$DATA/warden.db
WARDEN_KEY_PATH=$DATA/warden.key
# Headless server: no OS idle time; the "normal day" signal relies on check-ins.
CUSTODY_ACTIVITY=off
WARDEN_DEVICE_TOKEN=$token
EOF
  unset token
  echo "created $CONF/warden.env (device token inside; mode 600)"
fi
chmod 600 "$CONF"/*.env

echo "== dependencies, watcher image, app build"
uv sync --all-packages --frozen -q
scripts/build-watcher-image.sh >/dev/null
pnpm -C app install --frozen-lockfile --silent
pnpm -C app build >/dev/null

echo "== systemd user units"
cp deploy/systemd/custody-*.service deploy/systemd/custody-*.timer "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable custody-relay custody-warden custody-app >/dev/null 2>&1
systemctl --user enable --now custody-ufw-brain.timer custody-backup.timer >/dev/null 2>&1
systemctl --user enable custody-boot.service >/dev/null 2>&1  # runs restart.sh at boot
systemctl --user restart custody-relay custody-app
systemctl --user restart custody-warden
# Start at boot without a login session (NemoClaw's gateway unit needs this too).
if [ "$(loginctl show-user "$USER" -p Linger --value)" != "yes" ]; then
  sudo loginctl enable-linger "$USER"
fi

echo "== tailscale serve (tailnet only, HTTPS; never Funnel)"
# If Serve/HTTPS isn't enabled for the tailnet yet, `tailscale serve` prints an admin link and
# waits forever; give up after 20 s and show the link instead.
serve() {
  local out
  if ! out=$(timeout 20 sudo tailscale serve --bg --https=443 --set-path "$1" "$2" 2>&1); then
    echo "tailscale serve is not enabled for this tailnet. Approve it (one click), then re-run:"
    printf '%s\n' "$out" | grep -o 'https://login.tailscale.com[^ ]*' | head -1
    return 1
  fi
}
# /relay: the ciphertext mailbox, so a second Warden on the tailnet (Anna's Mac, docs/ANNA_SETUP.md)
# can reach it. Tailnet only, like the rest; the relay stores ciphertext only (THREAT_MODEL A6).
serve /api http://127.0.0.1:8000/api && serve /relay http://127.0.0.1:8100 \
  && serve / http://127.0.0.1:8300 && sudo tailscale serve status
echo "done. Device token: grep WARDEN_DEVICE_TOKEN $CONF/warden.env"
