"""SandboxDriver Protocol (ADR-0001): one OpenShell sandbox per watcher.

Only this package (`warden.sandbox`) may drive a real `openshell` CLI —
see AGENTS.md invariant #3. This module declares the interface only;
the real OpenShell-backed implementation lands in T-04.
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class SandboxHandle:
    name: str
    status: str


@dataclass(frozen=True, slots=True)
class ExecResult:
    stdout: str
    stderr: str
    exit_code: int


class SandboxDriver(Protocol):
    async def create(self, name: str, image: str) -> SandboxHandle: ...

    async def apply_policy(self, name: str, policy_yaml: str) -> None: ...

    async def write_file(self, name: str, path: str, content: str) -> None:
        """Place a file (the watcher's `/w/run.py`) inside the sandbox. Never on the host."""
        ...

    async def exec(self, name: str, command: list[str]) -> ExecResult: ...

    async def delete(self, name: str) -> None: ...
