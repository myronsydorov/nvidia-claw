#!/usr/bin/env bash
# Formats the file Claude just edited. It never blocks: formatting problems surface in `make lint`.
set -u
file=$(python3 -c 'import json,sys; d=json.load(sys.stdin); print(d.get("tool_input",{}).get("file_path",""))' 2>/dev/null)
[ -z "$file" ] || [ ! -f "$file" ] && exit 0
case "$file" in
  *.py)
    command -v uv >/dev/null && uv run --quiet ruff format "$file" >/dev/null 2>&1 && uv run --quiet ruff check --fix "$file" >/dev/null 2>&1 ;;
  *.ts|*.tsx|*.json|*.css)
    [ -d "$CLAUDE_PROJECT_DIR/app/node_modules" ] && pnpm -C "$CLAUDE_PROJECT_DIR/app" exec biome format --write "$file" >/dev/null 2>&1 ;;
esac
exit 0
