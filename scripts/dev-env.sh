#!/usr/bin/env bash
# `make dev` helper: make sure .env exists and has a device token for the local Warden.
# Writes a random one into .env (gitignored) the first time; never prints it.
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
[ -f .env ] || { cp .env.example .env; echo "created .env from .env.example"; }
if ! grep -qE '^WARDEN_DEVICE_TOKEN=.+' .env; then
  # Generated and written inside Python: the token never appears on a command line.
  python3 - <<'PY'
import pathlib, secrets
p = pathlib.Path(".env")
line = f"WARDEN_DEVICE_TOKEN={secrets.token_urlsafe(32)}"
lines = p.read_text().splitlines()
if any(l.startswith("WARDEN_DEVICE_TOKEN=") for l in lines):
    lines = [line if l.startswith("WARDEN_DEVICE_TOKEN=") else l for l in lines]
else:
    lines.append(line)
p.write_text("\n".join(lines) + "\n")
PY
  echo "wrote a new device token into .env (WARDEN_DEVICE_TOKEN): paste it into the app"
fi
chmod 600 .env
