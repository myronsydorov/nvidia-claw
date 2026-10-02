#!/usr/bin/env bash
# `make dev` helper: make sure .env exists and has a device token for the local Warden.
# Writes a random one into .env (gitignored) the first time; never prints it.
set -euo pipefail
cd "$(dirname "$0")/.."
umask 077
[ -f .env ] || { cp .env.example .env; echo "created .env from .env.example"; }
if ! grep -qE '^WARDEN_DEVICE_TOKEN=.+' .env; then
  token=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
  if grep -q '^WARDEN_DEVICE_TOKEN=' .env; then
    python3 - "$token" <<'PY'
import sys, pathlib
p = pathlib.Path(".env")
lines = [f"WARDEN_DEVICE_TOKEN={sys.argv[1]}" if l.startswith("WARDEN_DEVICE_TOKEN=") else l
         for l in p.read_text().splitlines()]
p.write_text("\n".join(lines) + "\n")
PY
  else
    echo "WARDEN_DEVICE_TOKEN=$token" >> .env
  fi
  echo "wrote a new device token into .env (WARDEN_DEVICE_TOKEN): paste it into the app"
fi
