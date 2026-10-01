"""The real SandboxDriver: one OpenShell sandbox per watcher (ADR-0001, T-04).

This is the only module that runs the `openshell` CLI (AGENTS invariant #3). Behaviour
pinned on OpenShell 0.0.116 by the T-04 spike:

- `sandbox create --from <image> --policy <file> --detach` returns before the sandbox is
  Ready; we poll `sandbox get -o json` for `phase == Ready`. The sandbox starts with the
  network-less baseline policy, so nothing can leave it before `apply_policy`.
- Filesystem paths can't be removed from a live sandbox's policy, only network rules
  changed: `policy set --wait` swaps in the generated policy, same baseline.
- `sandbox upload` and `sandbox exec` run as the `sandbox` user under Landlock; `exec`
  passes the command's exit code, stdout and stderr through, and waits on stdin unless it
  is closed, so every call gets stdin=DEVNULL.
- Denied egress shows up in `openshell logs <name>` as OCSF `DENIED` lines.

Only names of our own sandboxes (`cw-*` watchers, `cwd-*` dry runs) are accepted, so a bug
here can never touch the brain's sandbox. Watcher output is never logged.
"""

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import tempfile
import time
from pathlib import Path

import yaml

from warden.adapters.base import Endpoint
from warden.compiler.policy import BASELINE, WATCHER_BINARY, baseline_policy_yaml
from warden.sandbox.driver import ExecResult, SandboxHandle

log = logging.getLogger(__name__)

_NAME = re.compile(r"cwd?-[a-z0-9][a-z0-9-]{0,15}")  # CONTRACTS: cw-<short id>, ≤ 19 chars
_UPLOAD_PATH = re.compile(r"/w/[a-z0-9_]{1,32}\.py")
# The CLI gets only what it needs to find its gateway config and Docker: never the Warden's
# secrets (NVIDIA key, device token), which OpenShell could otherwise pick up as credentials.
_ENV_ALLOWLIST = (
    "PATH",
    "HOME",
    "USER",
    "LANG",
    "XDG_CONFIG_HOME",
    "XDG_RUNTIME_DIR",
    "DOCKER_HOST",
    "OPENSHELL_GATEWAY",
)
_DENIED = re.compile(r"\bDENIED\b")
_MAX_OUTPUT_BYTES = 256 * 1024  # watch_output caps stdout at 64 KiB; anything past this is noise

DEFAULT_IMAGE = "custody-watcher:latest"
CLI_TIMEOUT_S = 120.0
READY_TIMEOUT_S = 90.0
EXEC_TIMEOUT_S = 120


class OpenShellError(RuntimeError):
    """An `openshell` call failed. The message never holds watcher output."""


def _check_name(name: str) -> str:
    if not _NAME.fullmatch(name):
        raise ValueError(f"not a Custody watcher sandbox name: {name!r}")
    return name


def _check_policy(policy_yaml: str) -> None:
    """Defence in depth for invariant #2: a policy read back from the database is applied only
    if it is exactly what `generate_policy` makes: the fixed baseline, L7-enforced GET rules on
    valid declared endpoints, and the watcher interpreter as the only binary."""
    try:
        doc = yaml.safe_load(policy_yaml)
        if not isinstance(doc, dict):
            raise ValueError
        network = doc.pop("network_policies")
        if doc != BASELINE or not isinstance(network, dict):
            raise ValueError
        for key, entry in network.items():
            if set(entry) != {"name", "endpoints", "binaries"} or entry["name"] != key:
                raise ValueError
            if entry["binaries"] != [{"path": WATCHER_BINARY}]:
                raise ValueError
            for endpoint in entry["endpoints"]:
                if set(endpoint) != {"host", "port", "protocol", "enforcement", "rules"}:
                    raise ValueError
                if (endpoint["protocol"], endpoint["enforcement"]) != ("rest", "enforce"):
                    raise ValueError
                for rule in endpoint["rules"]:
                    if set(rule) != {"allow"} or set(rule["allow"]) != {"method", "path"}:
                        raise ValueError
                    # Re-validates host (no wildcard, no IP literal), GET-only, canonical path.
                    Endpoint(
                        host=endpoint["host"],
                        port=endpoint["port"],
                        method=rule["allow"]["method"],
                        path=rule["allow"]["path"],
                        why="-",
                    )
    except (ValueError, KeyError, TypeError, AttributeError, yaml.YAMLError):
        raise ValueError("refusing a policy that generate_policy would not have made") from None


class OpenShellDriver:
    def __init__(
        self,
        image: str | None = None,
        binary: str | None = None,
        cpu: str = "500m",
        memory: str = "256Mi",
    ) -> None:
        found = binary or os.environ.get("OPENSHELL_BIN") or shutil.which("openshell")
        if not found:
            raise RuntimeError("the openshell CLI is not on PATH (set OPENSHELL_BIN)")
        self._bin = found
        self._image = image or os.environ.get("CUSTODY_WATCHER_IMAGE", DEFAULT_IMAGE)
        self._cpu = cpu
        self._memory = memory

    async def _run(
        self, *args: str, timeout: float = CLI_TIMEOUT_S, check: bool = True
    ) -> ExecResult:
        proc = await asyncio.create_subprocess_exec(
            self._bin,
            *args,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env={k: os.environ[k] for k in _ENV_ALLOWLIST if k in os.environ} | {"NO_COLOR": "1"},
        )
        try:
            stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except BaseException:  # a timeout, or the caller's wait_for cancelling us
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            with contextlib.suppress(Exception):
                await asyncio.shield(proc.wait())
            raise
        result = ExecResult(
            stdout=stdout[:_MAX_OUTPUT_BYTES].decode("utf-8", "replace"),
            stderr=stderr[:_MAX_OUTPUT_BYTES].decode("utf-8", "replace"),
            exit_code=proc.returncode if proc.returncode is not None else -1,
        )
        if check and result.exit_code != 0:
            # args[0:2] is the subcommand ("sandbox create"); never the policy or file contents.
            raise OpenShellError(f"openshell {' '.join(args[:2])} exited {result.exit_code}")
        return result

    async def _phase(self, name: str) -> str | None:
        out = await self._run("sandbox", "get", name, "-o", "json", check=False, timeout=30)
        if out.exit_code != 0:
            return None
        try:
            phase = json.loads(out.stdout).get("phase")
        except (ValueError, AttributeError):
            return None
        return phase if isinstance(phase, str) else None

    async def _create(self, name: str, policy: Path) -> None:
        await self._run(
            "sandbox", "create",
            "--name", name,
            "--from", self._image,
            "--policy", str(policy),
            "--cpu", self._cpu,
            "--memory", self._memory,
            "--label", "custody=watcher",
            "--no-auto-providers",
            "--no-tty",
            "--detach",
        )  # fmt: skip

    async def create(self, name: str, image: str) -> SandboxHandle:
        """`image` is the logical name used by the compiler ("watcher-base"); the actual
        reference comes from CUSTODY_WATCHER_IMAGE (built by scripts/build-watcher-image.sh)."""
        _check_name(name)
        started = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="custody-") as tmp:
            policy = Path(tmp) / "baseline.yaml"
            policy.write_text(baseline_policy_yaml())
            try:
                await self._create(name, policy)
            except BaseException:
                # The CLI may have created it before failing or timing out: never leave it.
                with contextlib.suppress(Exception):
                    await asyncio.shield(self.delete(name))
                raise
        while (phase := await self._phase(name)) != "Ready":
            if phase in ("Error", "Failed") or time.monotonic() - started > READY_TIMEOUT_S:
                with contextlib.suppress(Exception):
                    await self.delete(name)
                raise OpenShellError(f"sandbox {name} did not become Ready (phase {phase})")
            await asyncio.sleep(0.25)
        log.info(
            "sandbox ready",
            extra={"sandbox": name, "ms": int((time.monotonic() - started) * 1000)},
        )
        return SandboxHandle(name=name, status="ready")

    async def apply_policy(self, name: str, policy_yaml: str) -> None:
        _check_name(name)
        _check_policy(policy_yaml)
        with tempfile.TemporaryDirectory(prefix="custody-") as tmp:
            policy = Path(tmp) / "policy.yaml"
            policy.write_text(policy_yaml)
            await self._run(
                "policy", "set", "--policy", str(policy), "--wait", "--timeout", "60", name,
                timeout=90,
            )  # fmt: skip

    async def write_file(self, name: str, path: str, content: str) -> None:
        _check_name(name)
        if not _UPLOAD_PATH.fullmatch(path):
            raise ValueError(f"refusing to upload outside /w/: {path!r}")
        with tempfile.TemporaryDirectory(prefix="custody-") as tmp:
            local = Path(tmp) / Path(path).name
            local.write_text(content)
            await self._run("sandbox", "upload", name, str(local), path)

    async def exec(self, name: str, command: list[str]) -> ExecResult:
        _check_name(name)
        return await self._run(
            "sandbox", "exec", "-n", name, "--no-tty", "--timeout", str(EXEC_TIMEOUT_S),
            "--", *command,
            timeout=EXEC_TIMEOUT_S + 15, check=False,
        )  # fmt: skip

    async def delete(self, name: str) -> None:
        _check_name(name)
        out = await self._run("sandbox", "delete", name, check=False)
        if out.exit_code != 0 and "not found" not in (out.stdout + out.stderr).lower():
            raise OpenShellError(f"openshell sandbox delete exited {out.exit_code}")

    async def ensure_running(self, name: str) -> bool:
        """Containers don't restart with the host, but OpenShell keeps the sandbox (policy and
        /w included): `sandbox start` brings it back in about a second (T-20)."""
        _check_name(name)
        phase = await self._phase(name)
        if phase is None:
            return False
        if phase != "Ready":
            await self._run("sandbox", "start", name)
            started = time.monotonic()
            while (phase := await self._phase(name)) != "Ready":
                if time.monotonic() - started > READY_TIMEOUT_S:
                    raise OpenShellError(f"sandbox {name} did not come back (phase {phase})")
                await asyncio.sleep(0.25)
        return True

    async def denials(self, name: str, since: str = "1h") -> list[str]:
        """OpenShell's own log lines for egress it denied in this sandbox (OCSF `DENIED`).

        They name the binary, host and path, never a body. Used by the spike and for
        evidence; not served over /api."""
        _check_name(name)
        out = await self._run(
            "logs", name, "-n", "1000", "--since", since, "--source", "sandbox",
            check=False, timeout=30,
        )  # fmt: skip
        return [line for line in out.stdout.splitlines() if _DENIED.search(line)]
