"""In-memory SandboxDriver used when CUSTODY_SANDBOX=mock. No openshell calls."""

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from warden.sandbox.driver import ExecResult, SandboxHandle


@dataclass
class _MockSandbox:
    handle: SandboxHandle
    policy_yaml: str | None = None


class MockDriver:
    def __init__(self) -> None:
        self._sandboxes: dict[str, _MockSandbox] = {}

    async def create(self, name: str, image: str) -> SandboxHandle:
        if name in self._sandboxes:
            raise ValueError(f"sandbox {name!r} already exists")
        handle = SandboxHandle(name=name, status="ready")
        self._sandboxes[name] = _MockSandbox(handle=handle)
        return handle

    async def apply_policy(self, name: str, policy_yaml: str) -> None:
        self._sandboxes[name].policy_yaml = policy_yaml

    async def exec(self, name: str, command: list[str]) -> ExecResult:
        if name not in self._sandboxes:
            raise KeyError(f"no such sandbox {name!r}")
        # A canned `ok` WatchResult so `make dev` shows a quietly watching worry.
        result = {
            "status": "ok",
            "summary": "All quiet (mock sandbox).",
            "evidence": {"source": "mock", "checked_at": datetime.now(UTC).isoformat(), "data": {}},
            "fear_came_true": None,
            "next_check_s": 3600,
        }
        return ExecResult(stdout=json.dumps(result), stderr="", exit_code=0)

    async def delete(self, name: str) -> None:
        del self._sandboxes[name]
