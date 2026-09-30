"""Turning a watcher's stdout into a WatchResult, shared by the scheduler and the dry run.

stdout is untrusted data: it is only ever parsed into a WatchResult and bounded,
never fed to a model and never logged.
"""

import json

from pydantic import ValidationError

from warden.models import WatchResult
from warden.sandbox.driver import ExecResult

RUN_COMMAND = ["python3", "/w/run.py"]
RUN_PATH = "/w/run.py"
MAX_STDOUT_CHARS = 64 * 1024  # anything bigger is not a WatchResult; don't even parse it
MAX_EVIDENCE_SOURCE_CHARS = 64
MAX_EVIDENCE_DATA_CHARS = 4096  # watched content must not be stored verbatim


class OutputProblem(Exception):
    """Why the output is not a usable WatchResult; `summary` is plain language for the user."""

    def __init__(self, summary: str) -> None:
        super().__init__(summary)
        self.summary = summary


def parse_output(out: ExecResult) -> WatchResult:
    if out.exit_code != 0:
        raise OutputProblem("The check stopped with an error.")
    if len(out.stdout) > MAX_STDOUT_CHARS:
        raise OutputProblem("The check gave an answer that was far too long.")
    try:
        result = WatchResult.model_validate(json.loads(out.stdout))
    except (ValueError, RecursionError, ValidationError):
        # ValueError covers JSONDecodeError and over-long int literals; RecursionError
        # covers deeply nested input.
        raise OutputProblem("The check gave an answer I couldn't read.") from None
    return bounded(result)


def bounded(result: WatchResult) -> WatchResult:
    """Cap the untrusted evidence before it is stored and served back out."""
    evidence = result.evidence
    data = evidence.data
    if len(json.dumps(data)) > MAX_EVIDENCE_DATA_CHARS:
        data = {"truncated": True}
    capped = evidence.model_copy(
        update={"source": evidence.source[:MAX_EVIDENCE_SOURCE_CHARS], "data": data}
    )
    return result.model_copy(update={"evidence": capped})
