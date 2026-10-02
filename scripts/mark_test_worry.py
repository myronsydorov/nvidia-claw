"""Mark a worry as a test, so the ledger doesn't count it or its watcher (CONTRACTS §5).

For worries created to test the system (e.g. the T-11 brain test), never for the person's own.
Append-only: adds one `test` timeline event and changes nothing else. It takes an online
backup of the database first. Run it with the Warden stopped:

    systemctl --user stop custody-warden
    uv run --package warden python scripts/mark_test_worry.py <worry_id> [db_path]
    systemctl --user start custody-warden
"""

import json
import os
import sqlite3
import sys
from datetime import UTC, datetime

TEXT = "Marked as a test of the system, not one of your worries. Not counted in your ledger."


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
    if any(e["kind"] == "test" for e in data["timeline"]):
        print("already marked")
        return 0
    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    backup = sqlite3.connect(f"{db}.bak-{stamp}-mark-test")
    conn.backup(backup)
    backup.close()
    os.chmod(f"{db}.bak-{stamp}-mark-test", 0o600)
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    data["timeline"].append({"at": now, "kind": "test", "text": TEXT})
    with conn:
        conn.execute("UPDATE worries SET data = ? WHERE id = ?", (json.dumps(data), worry_id))
    print(f"marked {worry_id}: status still {data['worry']['status']!r}, 1 event appended")
    print(f"backup: {db}.bak-{stamp}-mark-test")
    return 0


if __name__ == "__main__":
    sys.exit(main())
