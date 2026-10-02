#!/usr/bin/env bash
# Online, consistent snapshot of the Warden and relay databases (SQLite backup API), keeping
# the newest 14 of each. Run daily by custody-backup.timer; safe to run by hand any time.
set -euo pipefail
DATA="${CUSTODY_DATA:-$HOME/.local/share/custody}"
DEST="$DATA/backups"
umask 077
mkdir -p "$DEST"
stamp=$(date -u +%Y%m%d-%H%M%S)
for db in warden relay; do
  [ -f "$DATA/$db.db" ] || continue
  python3 - "$DATA/$db.db" "$DEST/$db-$stamp.db" <<'PY'
import sqlite3, sys
src = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
dst = sqlite3.connect(sys.argv[2])
src.backup(dst)
assert dst.execute("pragma integrity_check").fetchone()[0] == "ok"
dst.close(); src.close()
PY
  ls -1t "$DEST/$db-"*.db | tail -n +15 | xargs -r rm -f
  echo "backup: $DEST/$db-$stamp.db"
done
