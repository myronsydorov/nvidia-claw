#!/usr/bin/env bash
# Live evidence for the video, on the host: sandboxes, a generated policy, a denial in
# OpenShell's audit log, the brain's sandbox and the relay's ciphertext. Prints no secrets.
# Takes about 30 s (step 3 creates and deletes one throwaway probe sandbox).
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"
exec uv run --package warden python scripts/demo_evidence.py "$@"
