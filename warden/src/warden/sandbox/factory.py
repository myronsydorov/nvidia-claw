import os

from warden.sandbox.driver import SandboxDriver
from warden.sandbox.mock import MockDriver


def get_sandbox_driver() -> SandboxDriver:
    """CUSTODY_SANDBOX=mock for local development; `openshell` (or unset) for the real one."""
    mode = os.environ.get("CUSTODY_SANDBOX") or "openshell"
    if mode == "mock":
        return MockDriver()
    if mode == "openshell":
        # Imported lazily: the driver reads the compiler's policy helpers, which import us.
        from warden.sandbox.openshell import OpenShellDriver

        return OpenShellDriver()
    raise ValueError(f"CUSTODY_SANDBOX={mode!r}: expected 'mock' or 'openshell'")
