"""Dry run: the generated watcher, once, in a fresh throwaway sandbox (DESIGN §4 step 5).

create → apply the generated policy → write run.py → exec → delete (always). The
code never runs on the host (AGENTS invariant #1); everything goes through the
SandboxDriver (invariant #3).
"""

import asyncio
import logging
import secrets
from dataclasses import dataclass

from warden.adapters.base import Adapter
from warden.compiler.policy import generate_policy
from warden.sandbox.driver import ExecResult, SandboxDriver
from warden.watch_output import RUN_COMMAND, RUN_PATH, OutputProblem, parse_output

log = logging.getLogger(__name__)

DRY_RUN_TIMEOUT_S = 60.0
IMAGE = "watcher-base"


@dataclass(frozen=True)
class DryRunOutcome:
    ok: bool
    problem: str  # our own wording, safe to feed back; "" when ok
    exec_result: ExecResult | None  # for guard.dry_run_feedback; never stored or logged


def dry_run_sandbox_name() -> str:
    return f"cwd-{secrets.token_hex(4)}"  # distinct from watchers' cw-*, 12 chars


async def dry_run(
    driver: SandboxDriver,
    adapters: list[Adapter],
    code: str,
    timeout_s: float = DRY_RUN_TIMEOUT_S,
) -> DryRunOutcome:
    """Same adapters, same generator as the real watcher's policy; only the sandbox name differs."""
    name = dry_run_sandbox_name()
    policy_yaml, _ = generate_policy(adapters, name)
    created = False
    try:
        await driver.create(name, image=IMAGE)
        created = True
        await driver.apply_policy(name, policy_yaml)
        await driver.write_file(name, RUN_PATH, code)
        out = await asyncio.wait_for(driver.exec(name, RUN_COMMAND), timeout=timeout_s)
    except TimeoutError:
        return DryRunOutcome(False, f"run.py took longer than {int(timeout_s)} s", None)
    except Exception as exc:
        log.warning("dry run sandbox step failed", extra={"error": type(exc).__name__})
        return DryRunOutcome(False, "the sandbox could not run the watcher", None)
    finally:
        if created:
            try:
                await driver.delete(name)
            except Exception as exc:
                log.warning("dry run sandbox delete failed", extra={"error": type(exc).__name__})

    try:
        result = parse_output(out)
    except OutputProblem:
        if out.exit_code != 0:
            return DryRunOutcome(False, "run.py crashed", out)
        return DryRunOutcome(False, "run.py did not print exactly one valid WatchResult", out)
    if result.status == "error":
        return DryRunOutcome(False, "run.py reported that its check failed (status error)", out)
    return DryRunOutcome(True, "", out)
