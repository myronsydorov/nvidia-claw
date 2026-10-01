"""T-04 spike (ADR-0001), live on a NemoClaw/OpenShell host: `make spike`.

Through the real OpenShellDriver (never the CLI directly): create a watcher sandbox from the
custody-watcher image → apply the policy generated from two adapters → upload run.py → exec →
parse the WatchResult → read OpenShell's denial log → delete. Prints timings for ADR-0001 and
exits non-zero if any expectation fails. Watched content is never printed, only statuses.
"""

import asyncio
import json
import secrets
import subprocess
import sys
import time

from warden.adapters import ics_calendar, weather_openmeteo
from warden.compiler.policy import generate_policy
from warden.sandbox.driver import ExecResult
from warden.sandbox.openshell import OpenShellDriver
from warden.watch_output import RUN_COMMAND, RUN_PATH, parse_output

GCAL = (
    "https://calendar.google.com/calendar/ical/"
    "en.german%23holiday%40group.v.calendar.google.com/public/basic.ics"
)

# Our own probe (not a generated watcher): every request it makes, and what OpenShell did.
PROBE = f"""
import json
import httpx2 as httpx
from watcher_runtime.adapters import weather_openmeteo
from watcher_runtime.harness import emit

GCAL = {GCAL!r}
results = {{}}
def probe(name, url):
    try:
        with httpx.Client(timeout=20) as c:
            results[name] = c.get(url).status_code
    except Exception as exc:
        results[name] = type(exc).__name__

weather = weather_openmeteo.fetch(52.52, 13.41)
results["declared: open-meteo /v1/forecast"] = "ok" if weather else "empty"
probe("declared: Google ICS, percent-encoded", GCAL)
probe("undeclared host: example.com", "https://example.com/")
probe("undeclared path: open-meteo /v1/archive", "https://api.open-meteo.com/v1/archive")
probe("encoded slash", "https://api.open-meteo.com/v1%2Fforecast")
with open("/tmp/probe.json", "w") as fh:
    json.dump(results, fh)
emit("ok", "spike probe finished", "spike", results, next_check_s=300)
"""

EXPECT = {
    "declared: open-meteo /v1/forecast": "ok",
    "declared: Google ICS, percent-encoded": 200,
    "undeclared host: example.com": "ProxyError",
    "undeclared path: open-meteo /v1/archive": 403,
    "encoded slash": "RemoteProtocolError",
}


def _memory(name: str) -> str:
    try:
        out = subprocess.run(
            ["docker", "stats", "--no-stream", "--format", "{{.Name}} {{.MemUsage}}"],
            capture_output=True, text=True, timeout=30, check=False,
        )  # fmt: skip
    except OSError:
        return "n/a"
    for line in out.stdout.splitlines():
        if f"--{name}-" in line:
            return line.split(" ", 1)[1].split(" / ")[0]
    return "n/a"


async def main() -> int:
    driver = OpenShellDriver()
    name = f"cw-spike-{secrets.token_hex(3)}"
    adapters = [
        weather_openmeteo.ADAPTER,
        ics_calendar.declare(url=GCAL, why="check the holiday calendar"),
    ]
    policy_yaml, summary = generate_policy(adapters, name)
    print("permission card:")
    for line in summary:
        print(f"  {line.method} {line.host}{line.path}  ({line.why})")

    timings: dict[str, float] = {}
    failures: list[str] = []
    t = time.monotonic()
    await driver.create(name, image="watcher-base")
    timings["create → Ready"] = time.monotonic() - t
    try:
        timings["RAM idle"] = 0
        idle_ram = _memory(name)
        t = time.monotonic()
        await driver.apply_policy(name, policy_yaml)
        timings["policy set --wait"] = time.monotonic() - t
        t = time.monotonic()
        await driver.write_file(name, RUN_PATH, PROBE)
        timings["upload run.py"] = time.monotonic() - t
        t = time.monotonic()
        out: ExecResult = await driver.exec(name, RUN_COMMAND)
        timings["exec run.py"] = time.monotonic() - t
        result = parse_output(out)
        print(f"WatchResult parsed: status={result.status} summary={result.summary!r}")
        for probe, got in result.evidence.data.items():
            want = EXPECT.get(probe)
            mark = "ok " if got == want else "BAD"
            if got != want:
                failures.append(f"{probe}: got {got!r}, want {want!r}")
            print(f"  [{mark}] {probe:42} -> {got}")
        await asyncio.sleep(12)  # OpenShell flushes sandbox logs every ~10 s
        denials = await driver.denials(name, since="5m")
        print(f"OpenShell denial log ({len(denials)} lines):")
        for line in denials:
            print("  " + line[:220])
        if not any("example.com" in line for line in denials):
            failures.append("no DENIED log line for example.com")
    finally:
        t = time.monotonic()
        await driver.delete(name)
        timings["delete"] = time.monotonic() - t

    print("timings:")
    for key, value in timings.items():
        if key == "RAM idle":
            print(f"  {key:20} {idle_ram}")
        else:
            print(f"  {key:20} {value:.2f} s")
    print(json.dumps({"failures": failures}))
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
