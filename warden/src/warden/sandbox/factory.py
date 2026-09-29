import os

from warden.sandbox.driver import SandboxDriver
from warden.sandbox.mock import MockDriver


def get_sandbox_driver() -> SandboxDriver:
    mode = os.environ.get("CUSTODY_SANDBOX")
    if mode == "mock":
        return MockDriver()
    raise NotImplementedError(
        f"CUSTODY_SANDBOX={mode!r} has no driver yet; the real OpenShell driver lands in T-04. "
        "Set CUSTODY_SANDBOX=mock for local development."
    )
