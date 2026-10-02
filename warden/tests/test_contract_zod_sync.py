"""Field-by-field parity between warden/src/warden/models.py (Pydantic) and
app/src/api/schemas.ts (zod), for every wire shape that has a zod counterpart.

Cross-toolchain by nature: shells out to Node to export the zod schemas as
JSON Schema (via app/scripts/export-schemas.ts). Skips if node/pnpm aren't on
PATH -- `make test` always has both, so this is exercised for real there.
"""

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

import pytest
from pydantic import BaseModel

from warden import models

APP_DIR = Path(__file__).resolve().parents[2] / "app"

MODELS: dict[str, type[BaseModel]] = {
    "HealthResponse": models.HealthResponse,
    "Worry": models.Worry,
    "PermissionLine": models.PermissionLine,
    "WatchResult": models.WatchResult,
    "Watcher": models.Watcher,
    "TimelineEvent": models.TimelineEvent,
    "WorrySummary": models.WorrySummary,
    "WorryDetail": models.WorryDetail,
    "WorryCreateRequest": models.WorryCreateRequest,
    "OutcomeRequest": models.OutcomeRequest,
    "Peer": models.Peer,
    "PairingStartRequest": models.PairingStartRequest,
    "PairingStartResponse": models.PairingStartResponse,
    "PairingStatusResponse": models.PairingStatusResponse,
    "PairingJoinRequest": models.PairingJoinRequest,
    "ReassuranceAnswer": models.ReassuranceAnswer,
    "PrivacyReceipt": models.PrivacyReceipt,
    "PeopleListItem": models.PeopleListItem,
    "AskPeerRequest": models.AskPeerRequest,
    "AskPeerResponse": models.AskPeerResponse,
    "SharingRule": models.SharingRule,
    "QuestionLogEntry": models.QuestionLogEntry,
    "SharingRulesResponse": models.SharingRulesResponse,
    "PushSubscription": models.PushSubscription,
    "LedgerResponse": models.LedgerResponse,
    "TalkRequest": models.TalkRequest,
    "TalkReply": models.TalkReply,
    "DailyClose": models.DailyClose,
    "Event": models.Event,
}


def _node_supports_strip_types() -> bool:
    """--experimental-strip-types needs Node >=22.6 (this repo pins Node 22 via
    .nvmrc/CI, but a reviewer's or contributor's default shell `node` may be older)."""
    version = subprocess.run(["node", "--version"], capture_output=True, text=True, timeout=5)
    match = re.match(r"v(\d+)\.(\d+)", version.stdout)
    if not match:
        return False
    major, minor = int(match.group(1)), int(match.group(2))
    return (major, minor) >= (22, 6)


@pytest.fixture(scope="module")
def zod_schemas() -> dict[str, Any]:
    if shutil.which("node") is None or shutil.which("pnpm") is None:
        pytest.skip("node/pnpm not on PATH; this cross-toolchain test needs both")
    if not _node_supports_strip_types():
        pytest.skip(
            "node on PATH is older than 22.6 (no --experimental-strip-types); "
            "run `nvm use 22` (see .nvmrc) for this cross-toolchain test"
        )
    result = subprocess.run(
        ["node", "--experimental-strip-types", "scripts/export-schemas.ts"],
        cwd=APP_DIR,
        capture_output=True,
        text=True,
        timeout=30,
    )
    if result.returncode != 0:
        pytest.fail(f"app/scripts/export-schemas.ts failed:\n{result.stderr}")
    return dict(json.loads(result.stdout))


def _resolve(schema: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    """Inline Pydantic's $ref/$defs so it's comparable to zod's fully-inlined output."""
    if "$ref" in schema:
        return _resolve(defs[schema["$ref"].rsplit("/", 1)[-1]], defs)
    if "anyOf" in schema:
        return {**schema, "anyOf": [_resolve(b, defs) for b in schema["anyOf"]]}
    return schema


_NUMERIC = {"integer", "number"}


def _type_category(schema: dict[str, Any]) -> str:
    """Collapse a JSON Schema fragment to a coarse type category for comparison."""
    if "const" in schema:
        return "string" if isinstance(schema["const"], str) else "literal"
    if "enum" in schema:
        return "string"
    if "type" in schema:
        t: object = schema["type"]
        if isinstance(t, list):
            non_null = [x for x in t if x != "null"]
            return str(non_null[0]) if non_null else "null"
        return str(t)
    if "anyOf" in schema:
        non_null = [b for b in schema["anyOf"] if b.get("type") != "null"]
        if non_null:
            return _type_category(non_null[0])
    return "unknown"


def _categories_compatible(a: str, b: str) -> bool:
    return a == b or (a in _NUMERIC and b in _NUMERIC)


@pytest.mark.parametrize("model_name", sorted(MODELS))
def test_zod_schema_matches_pydantic_model_fields(
    model_name: str, zod_schemas: dict[str, Any]
) -> None:
    assert model_name in zod_schemas, (
        f"app/src/api/schemas.ts exports no zod schema for {model_name}"
    )

    pydantic_schema = MODELS[model_name].model_json_schema()
    defs = pydantic_schema.get("$defs", {})
    zod_schema = zod_schemas[model_name]

    pydantic_fields = set(pydantic_schema["properties"])
    zod_fields = set(zod_schema["properties"])
    assert pydantic_fields == zod_fields, (
        f"{model_name}: field mismatch -- "
        f"Pydantic-only: {sorted(pydantic_fields - zod_fields)}; "
        f"zod-only: {sorted(zod_fields - pydantic_fields)}"
    )

    for field in sorted(pydantic_fields):
        p_field = _resolve(pydantic_schema["properties"][field], defs)
        p_cat = _type_category(p_field)
        z_cat = _type_category(zod_schema["properties"][field])
        assert _categories_compatible(p_cat, z_cat), (
            f"{model_name}.{field}: type mismatch (pydantic={p_cat!r}, zod={z_cat!r})"
        )
