#!/usr/bin/env bash
# Build the watcher base image into the local Docker daemon, tagged with the runtime's content
# hash so a code change always means a new tag. Prints the image reference on the last line.
set -euo pipefail
cd "$(dirname "$0")/.."
export PATH="$HOME/.local/bin:$PATH"

uv export --package watcher_runtime --no-dev --no-emit-project --no-emit-workspace \
  --format requirements-txt --quiet > watcher_runtime/image/requirements.txt
rm -rf watcher_runtime/image/dist
uv build --package watcher_runtime --wheel --quiet -o watcher_runtime/image/dist
hash=$(cd watcher_runtime && find image/Dockerfile image/requirements.txt pyproject.toml src -type f \
  ! -path '*__pycache__*' -print0 | sort -z | xargs -0 sha256sum | sha256sum | cut -c1-12)
ref="custody-watcher:$hash"
if ! docker image inspect "$ref" >/dev/null 2>&1; then
  docker build -q -f watcher_runtime/image/Dockerfile -t "$ref" watcher_runtime >&2
fi
docker tag "$ref" custody-watcher:latest
echo "$ref"
