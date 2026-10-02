"""What a judge would want to see, live, for the video (scripts/demo-evidence.sh runs this).

1. One OpenShell sandbox per running watcher.  2. One watcher's generated policy.
3. An undeclared host being denied, from OpenShell's own log.  4. The brain's sandbox.
5. The relay holding only ciphertext.

Every OpenShell call goes through warden.sandbox.openshell (AGENTS #3). It never prints a
token, a key or a payload body. Step 3 runs our own probe in a throwaway `cwd-*` sandbox with
the same generated policy as a real watcher, then deletes it; real watchers are untouched.
"""

import asyncio
import collections
import json
import math
import os
import secrets
import sqlite3
import subprocess
import sys
import urllib.request
from pathlib import Path

from warden.sandbox.openshell import OpenShellDriver
from warden.watch_output import RUN_COMMAND, RUN_PATH

HOME = Path.home()
WARDEN = "http://127.0.0.1:8000"
RELAY_DB = HOME / ".local/share/custody/relay.db"
BOLD, DIM, GREEN, RED, OFF = (
    ("\033[1m", "\033[2m", "\033[32m", "\033[31m", "\033[0m") if sys.stdout.isatty() else ("",) * 5
)

PROBE = """
import json
import httpx2 as httpx
seen = {}
for name, url in [("undeclared host example.com", "https://example.com/")]:
    try:
        with httpx.Client(timeout=15) as c:
            seen[name] = c.get(url).status_code
    except Exception as exc:
        seen[name] = type(exc).__name__
print(json.dumps(seen))
"""


def title(n: int, text: str) -> None:
    print(f"\n{BOLD}{'━' * 72}\n {n}  {text}\n{'━' * 72}{OFF}")


def ok(text: str) -> None:
    print(f"  {GREEN}✔{OFF} {text}")


def bad(text: str) -> None:
    print(f"  {RED}✘{OFF} {text}")


def token() -> str:
    for line in (HOME / ".config/custody/warden.env").read_text().splitlines():
        if line.startswith("WARDEN_DEVICE_TOKEN="):
            return line.split("=", 1)[1].strip()
    raise SystemExit("no WARDEN_DEVICE_TOKEN in ~/.config/custody/warden.env")


def api(path: str) -> object:
    req = urllib.request.Request(WARDEN + path, headers={"Authorization": f"Bearer {token()}"})
    with urllib.request.urlopen(req, timeout=10) as res:
        return json.loads(res.read())


def short(text: str, n: int = 52) -> str:
    return text if len(text) <= n else text[: n - 1] + "…"


async def sandboxes(driver: OpenShellDriver) -> list[dict]:  # type: ignore[type-arg]
    title(1, "One OpenShell sandbox per running watcher")
    rows = await driver.list_sandboxes()
    watching = []
    for item in api("/api/worries"):  # type: ignore[attr-defined]
        if item["worry"]["status"] in ("watching", "needs_you"):
            watching.append(api(f"/api/worries/{item['worry']['id']}"))
    by_name = {name: phase for name, phase, _ in rows}
    print(f"  {'SANDBOX':<16} {'PHASE':<8} WATCHES")
    for d in watching:
        w = d["watcher"]
        print(f"  {w['sandbox_name']:<16} {by_name.get(w['sandbox_name'], 'MISSING'):<8} "
              f"{short(d['worry']['text'])}")  # fmt: skip
    for name, phase, watcher in rows:
        if not watcher:
            print(f"  {name:<16} {phase:<8} {DIM}the brain (OpenClaw agent), not a watcher{OFF}")
    expected = {d["watcher"]["sandbox_name"] for d in watching}
    actual = {name for name, _, watcher in rows if watcher and name.startswith("cw-")}
    if expected == actual and all(by_name.get(n) == "Ready" for n in expected):
        ok(f"{len(expected)} running watchers, {len(actual)} watcher sandboxes, all Ready, "
           "no strays")  # fmt: skip
    else:
        bad(f"watchers {sorted(expected)} vs sandboxes {sorted(actual)}")
    return watching


def policy(watching: list[dict]) -> dict:  # type: ignore[type-arg]
    title(2, "A watcher's generated policy (from its adapters' declarations only)")
    pick = next((d for d in watching if "open-meteo" in d["watcher"]["policy_yaml"]), watching[0])
    w = pick["watcher"]
    print(f"  {DIM}worry:{OFF}   {short(pick['worry']['text'], 60)}")
    print(f"  {DIM}sandbox:{OFF} {w['sandbox_name']}   {DIM}approved by you on the card:{OFF}")
    for line in w["policy_summary"]:
        print(f"           {line['method']} {line['host']}{line['path']}")
    print()
    for line in w["policy_yaml"].rstrip().splitlines():
        print(f"    {line}")
    return pick


async def denial(driver: OpenShellDriver, pick: dict) -> None:  # type: ignore[type-arg]
    title(3, "An undeclared host, denied by OpenShell (its own audit log)")
    w = pick["watcher"]
    real = []
    for d in [pick]:
        real += await driver.denials(d["watcher"]["sandbox_name"], since="24h")
    if real:
        print(f"  {DIM}from the real watcher {w['sandbox_name']}, last 24 h:{OFF}")
        for line in real[-3:]:
            print(f"    {line.strip()}")
    name = f"cwd-proof-{secrets.token_hex(3)}"
    print(f"  {DIM}live probe: throwaway sandbox {name}, the same policy as {w['sandbox_name']},"
          f" asks for https://example.com/ …{OFF}")  # fmt: skip
    try:
        await driver.create(name, image="watcher-base")
        await driver.apply_policy(name, w["policy_yaml"])
        await driver.write_file(name, RUN_PATH, PROBE)
        result = await driver.exec(name, RUN_COMMAND)
        print(f"  {DIM}the probe saw:{OFF} {result.stdout.strip()}")
        lines: list[str] = []
        for _ in range(15):  # OpenShell flushes its log a moment after the request
            lines = [x for x in await driver.denials(name, since="5m") if "example.com" in x]
            if lines:
                break
            await asyncio.sleep(1)
        for line in lines:
            print(f"    {BOLD}{line.strip()}{OFF}")
        if any("example.com" in line for line in lines):
            ok("example.com is not in the policy: refused, and logged by OpenShell")
        else:
            bad("no DENIED line for example.com")
    finally:
        try:
            await driver.delete(name)
            print(f"  {DIM}{name} deleted{OFF}")
        except Exception as exc:
            bad(f"could not delete the probe sandbox ({type(exc).__name__}): "
                f"run  openshell sandbox delete {name}")  # fmt: skip


def brain() -> None:
    title(4, "The brain: OpenClaw in its own OpenShell sandbox (NemoClaw)")
    out = subprocess.run(
        ["nemoclaw", "custody-brain", "status"], capture_output=True, text=True, timeout=90
    ).stdout
    keep = ("Sandbox:", "Model:", "Provider:", "Inference:", "OpenShell:", "Phase:")
    for line in out.splitlines():
        _, _, value = line.strip().partition(":")
        if line.strip().startswith(keep) and value.strip() and "key" not in line.lower():
            print(f"  {line.strip()}")
    print(f"  {DIM}its chat endpoint listens on 127.0.0.1:18789 only "
          f"(scripts/check-gateway.sh){OFF}")  # fmt: skip


def relay() -> None:
    title(5, "The relay stores ciphertext only")
    conn = sqlite3.connect(f"file:{RELAY_DB}?mode=ro", uri=True)
    cols = [r[1] for r in conn.execute("pragma table_info(messages)")]
    print(f"  {DIM}columns:{OFF} {', '.join(cols)}")
    rows = conn.execute(
        "select id, recipient, sender, ciphertext, ts from messages order by id"
    ).fetchall()
    if not rows:
        print('  (empty: messages expire after 24 h. Ask "Is Anna OK?" and run this again)')
        return
    words = [b"normal", b"unusual", b"help", b"unknown", b"active_as_usual", b"not_enough_data",
             b"level", b"reason", b"pair_offer", b"pair_accept", b'"q"', b'"t"']  # fmt: skip
    print(f"  {'ID':>3}  {'TO':<10} {'FROM':<10} {'BYTES':>5}  {'BITS/BYTE':>9}  FIRST BYTES")
    hits = 0
    for mid, to, frm, ct, _ts in rows:
        n = len(ct)
        ent = -sum(c / n * math.log2(c / n) for c in collections.Counter(ct).values())
        hits += sum(w in ct for w in words)
        print(f"  {mid:>3}  {to[:8]}… {frm[:8]}… {n:>5}  {ent:>9.2f}  {ct[:12].hex()}…")
    if hits == 0:
        ok(f"{len(rows)} messages, key ids + timestamps + opaque bytes. No vocabulary word, no"
           " JSON field name in any of them")  # fmt: skip
    else:
        bad(f"{hits} plaintext markers found")


async def main() -> None:
    os.environ.setdefault("OPENSHELL_BIN", str(HOME / ".local/bin/openshell"))
    os.environ.setdefault("CUSTODY_WATCHER_IMAGE", "custody-watcher:latest")
    driver = OpenShellDriver()
    print(f"{BOLD}Custody: live evidence from the host{OFF}  {DIM}(no secrets printed){OFF}")
    watching = await sandboxes(driver)
    if watching:
        pick = policy(watching)
        await denial(driver, pick)
    brain()
    relay()
    print()


if __name__ == "__main__":
    asyncio.run(main())
