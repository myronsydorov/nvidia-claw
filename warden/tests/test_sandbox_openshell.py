"""OpenShellDriver against a fake `openshell` CLI: the argv it sends, never a live host.

The live check (a real sandbox, a real denial in the logs) is `make spike`.
"""

import asyncio
import json
import stat
import sys
from pathlib import Path

import pytest
import yaml
from warden.adapters.base import Adapter, Endpoint
from warden.compiler.policy import generate_policy
from warden.sandbox.openshell import OpenShellDriver, OpenShellError

FAKE = """#!{python}
import json, os, sys
here = os.path.dirname(os.path.abspath(sys.argv[0]))
log = os.path.join(here, "calls.jsonl")  # config lives next to the binary: the driver
mode_file = os.path.join(here, "mode")    # passes the CLI an env allowlist only
args = sys.argv[1:]
record = {{"args": args, "stdin_tty": os.isatty(0), "env_keys": sorted(os.environ)}}
for a in args:
    if a.endswith((".yaml", ".py")) and os.path.exists(a):
        record.setdefault("files", {{}})[os.path.basename(a)] = open(a).read()
with open(log, "a") as fh:
    fh.write(json.dumps(record) + "\\n")
mode = open(mode_file).read() if os.path.exists(mode_file) else ""
if args[:2] == ["sandbox", "get"]:
    print(json.dumps({{"name": args[2], "phase": "Ready"}}))
elif args[:2] == ["sandbox", "exec"]:
    if mode == "exit3":
        sys.stdout.write("partial"); sys.stderr.write("boom"); sys.exit(3)
    print('{{"status": "ok"}}')
elif args[:2] == ["sandbox", "create"] and mode == "create_fails":
    sys.stderr.write("secret-looking detail"); sys.exit(1)
elif args[:2] == ["sandbox", "delete"] and mode == "gone":
    sys.stderr.write("Error: sandbox not found"); sys.exit(1)
elif args[:2] == ["sandbox", "list"]:
    brain = {{"name": "custody-brain", "phase": "Ready", "labels": {{}}}}
    watcher = {{"name": "cw-abc123", "phase": "Ready", "labels": {{"custody": "watcher"}}}}
    print(json.dumps([brain, watcher]))
elif args[0] == "logs":
    print("[1] [sandbox] [OCSF ] NET:OPEN [MED] DENIED python3.12(53) -> example.com:443")
    print("[2] [sandbox] [INFO ] something else")
"""

DHL = Adapter(
    name="parcel_dhl",
    endpoints=[Endpoint(host="api-eu.dhl.com", path="/track/shipments", why="check parcel status")],
    description="Track a DHL shipment",
)


@pytest.fixture
def fake(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[OpenShellDriver, Path]:
    binary = tmp_path / "openshell"
    binary.write_text(FAKE.format(python=sys.executable))
    binary.chmod(binary.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "calls.jsonl"
    return OpenShellDriver(image="custody-watcher:test", binary=str(binary)), log


def _calls(log: Path) -> list[dict]:  # type: ignore[type-arg]
    return [json.loads(line) for line in log.read_text().splitlines()]


def test_full_lifecycle_sends_the_expected_commands(fake: tuple[OpenShellDriver, Path]) -> None:
    driver, log = fake
    policy_yaml, _ = generate_policy([DHL], "cw-abc123")

    async def run() -> str:
        await driver.create("cw-abc123", image="watcher-base")
        await driver.apply_policy("cw-abc123", policy_yaml)
        await driver.write_file("cw-abc123", "/w/run.py", "print('hi')\n")
        out = await driver.exec("cw-abc123", ["python3", "/w/run.py"])
        await driver.delete("cw-abc123")
        return out.stdout

    assert json.loads(asyncio.run(run())) == {"status": "ok"}
    calls = _calls(log)
    create = calls[0]["args"]
    assert create[:4] == ["sandbox", "create", "--name", "cw-abc123"]
    assert create[create.index("--from") + 1] == "custody-watcher:test"
    assert {"--detach", "--no-tty", "--no-auto-providers"} <= set(create)
    # Created network-less: the baseline policy has no network_policies at all.
    baseline = yaml.safe_load(calls[0]["files"]["baseline.yaml"])
    assert baseline["network_policies"] == {}
    assert calls[1]["args"][:2] == ["sandbox", "get"]
    policy_call = calls[2]
    assert policy_call["args"][:2] == ["policy", "set"] and "--wait" in policy_call["args"]
    assert policy_call["args"][-1] == "cw-abc123"
    assert policy_call["files"]["policy.yaml"] == policy_yaml
    upload = calls[3]
    assert upload["args"][:3] == ["sandbox", "upload", "cw-abc123"]
    assert upload["args"][-1] == "/w/run.py"
    assert upload["files"]["run.py"] == "print('hi')\n"
    exec_args = calls[4]["args"]
    assert exec_args[:4] == ["sandbox", "exec", "-n", "cw-abc123"]
    assert exec_args[exec_args.index("--") + 1 :] == ["python3", "/w/run.py"]
    assert calls[5]["args"] == ["sandbox", "delete", "cw-abc123"]
    assert not any(c["stdin_tty"] for c in calls)


@pytest.mark.parametrize(
    "name",
    ["custody-brain", "cw-", "cw-UPPER", "cw-a;rm", "x-abc", "cw-" + "a" * 17, "cw-abc\n"],
)
def test_refuses_names_that_are_not_ours(fake: tuple[OpenShellDriver, Path], name: str) -> None:
    driver, log = fake
    calls = (driver.create(name, "watcher-base"), driver.delete(name), driver.exec(name, ["x"]))
    for call in calls:
        with pytest.raises(ValueError):
            asyncio.run(call)
    assert not log.exists()


@pytest.mark.parametrize(
    "path", ["/etc/passwd", "/w/../etc/x.py", "/w/run.sh", "/sandbox/run.py", "/w/run.py\n"]
)
def test_refuses_uploads_outside_w(fake: tuple[OpenShellDriver, Path], path: str) -> None:
    driver, _ = fake
    with pytest.raises(ValueError):
        asyncio.run(driver.write_file("cw-abc123", path, "x"))


POLICY, _ = generate_policy([DHL], "cw-abc123")


@pytest.mark.parametrize(
    "widened",
    [
        POLICY.replace("path: /track/shipments", "path: /**"),
        POLICY.replace("path: /track/shipments", "path: /track/a%40b"),  # not canonical
        POLICY.replace("method: GET", "method: POST"),
        POLICY.replace("host: api-eu.dhl.com", "host: '*.dhl.com'"),
        POLICY.replace("host: api-eu.dhl.com", "host: 169.254.169.254"),
        POLICY.replace("enforcement: enforce", "enforcement: audit"),
        POLICY.replace("protocol: rest", "protocol: tcp"),
        POLICY.replace("protocol: rest", "protocol: rest\n      allow_encoded_slash: true"),
        POLICY.replace("/usr/local/bin/python3.12", "/bin/bash"),
        POLICY.replace("compatibility: strict", "compatibility: best_effort"),
        POLICY.replace("  - /etc\n", "  - /etc\n  - /home\n"),
        POLICY.replace("run_as_user: sandbox", "run_as_user: root"),
        "network_policies: {}\n",
        "[]",
        "{{{",
    ],
)
def test_refuses_a_policy_generate_policy_would_not_make(
    fake: tuple[OpenShellDriver, Path], widened: str
) -> None:
    driver, log = fake
    assert widened != POLICY
    with pytest.raises(ValueError):
        asyncio.run(driver.apply_policy("cw-abc123", widened))
    assert not log.exists()


def test_the_cli_never_sees_the_wardens_secrets(
    fake: tuple[OpenShellDriver, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    driver, log = fake
    monkeypatch.setenv("NVIDIA_API_KEY", "nvapi-test")
    monkeypatch.setenv("WARDEN_DEVICE_TOKEN", "tok")
    monkeypatch.setenv("OPENCLAW_GATEWAY_TOKEN", "gw")
    asyncio.run(driver.exec("cw-abc123", ["true"]))
    env_keys = set(_calls(log)[0]["env_keys"])
    assert not env_keys & {"NVIDIA_API_KEY", "WARDEN_DEVICE_TOKEN", "OPENCLAW_GATEWAY_TOKEN"}


def test_a_failed_create_cleans_up(
    fake: tuple[OpenShellDriver, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    driver, log = fake
    (log.parent / "mode").write_text("create_fails")
    with pytest.raises(OpenShellError):
        asyncio.run(driver.create("cw-abc123", "watcher-base"))
    assert _calls(log)[-1]["args"] == ["sandbox", "delete", "cw-abc123"]


def test_exec_passes_exit_code_and_streams_through(
    fake: tuple[OpenShellDriver, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    driver, log = fake
    (log.parent / "mode").write_text("exit3")
    out = asyncio.run(driver.exec("cw-abc123", ["python3", "/w/run.py"]))
    assert (out.exit_code, out.stdout, out.stderr) == (3, "partial", "boom")


def test_cli_failure_raises_without_echoing_its_output(
    fake: tuple[OpenShellDriver, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    driver, log = fake
    (log.parent / "mode").write_text("create_fails")
    with pytest.raises(OpenShellError) as info:
        asyncio.run(driver.create("cw-abc123", "watcher-base"))
    assert "secret-looking" not in str(info.value)


def test_delete_of_a_missing_sandbox_is_not_an_error(
    fake: tuple[OpenShellDriver, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    driver, log = fake
    (log.parent / "mode").write_text("gone")
    asyncio.run(driver.delete("cw-abc123"))


def test_denials_returns_only_denied_lines(fake: tuple[OpenShellDriver, Path]) -> None:
    driver, _ = fake
    lines = asyncio.run(driver.denials("cw-abc123"))
    assert len(lines) == 1 and "DENIED" in lines[0] and "example.com" in lines[0]


def test_a_cancelled_exec_kills_the_cli(tmp_path: Path) -> None:
    slow = tmp_path / "openshell"
    slow.write_text(f"#!{sys.executable}\nimport time\ntime.sleep(30)\n")
    slow.chmod(0o755)
    driver = OpenShellDriver(binary=str(slow))

    async def run() -> None:
        with pytest.raises(TimeoutError):
            await asyncio.wait_for(driver.exec("cw-abc123", ["x"]), timeout=0.5)

    asyncio.run(run())


def test_ensure_running_reports_ready_sandboxes(fake: tuple[OpenShellDriver, Path]) -> None:
    driver, log = fake
    assert asyncio.run(driver.ensure_running("cw-abc123")) is True
    assert [c["args"][:2] for c in _calls(log)] == [["sandbox", "get"]]


def test_list_sandboxes_is_read_only_and_marks_watchers(fake: tuple[OpenShellDriver, Path]) -> None:
    driver, log = fake
    rows = asyncio.run(driver.list_sandboxes())
    assert rows == [("custody-brain", "Ready", False), ("cw-abc123", "Ready", True)]
    assert [c["args"] for c in _calls(log)] == [["sandbox", "list", "-o", "json"]]
