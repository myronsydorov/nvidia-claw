"""Mark a worry as a build failure so the ledger doesn't count it (S7 incident, 2026-10-02).

Append-only: adds one `failed` timeline event and changes nothing else (status, text,
resolution, earlier events and the watcher row stay as they are). The ledger skips any worry
with a `failed` event that was never approved (CONTRACTS §5). Run it with the Warden stopped:

    systemctl --user stop custody-warden
    uv run --package warden python scripts/mark_build_failure.py <worry_id> [db_path]
    systemctl --user start custody-warden
"""

import json
import os
import sqlite3
import sys
from datetime import UTC, datetime

TEXT = "Marked as a failed build (it was parked by mistake). Not counted in your ledger."


def main() -> int:
    worry_id = sys.argv[1]
    db = (
        sys.argv[2] if len(sys.argv) > 2 else os.path.expanduser("~/.local/share/custody/warden.db")
    )
    conn = sqlite3.connect(db)
    row = conn.execute("SELECT data FROM worries WHERE id = ?", (worry_id,)).fetchone()
    if row is None:
        print(f"no worry {worry_id}")
        return 1
    data = json.loads(row[0])
    if any(e["kind"] == "failed" for e in data["timeline"]):
        print("already marked")
        return 0
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    data["timeline"].append({"at": now, "kind": "failed", "text": TEXT})
    with conn:
        conn.execute("UPDATE worries SET data = ? WHERE id = ?", (json.dumps(data), worry_id))
    print(f"marked {worry_id}: status still {data['worry']['status']!r}, 1 event appended")
    return 0


if __name__ == "__main__":
    sys.exit(main())
