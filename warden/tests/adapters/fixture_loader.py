import json
from pathlib import Path
from typing import Any

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


def load_json_fixture(adapter_name: str, filename: str) -> Any:
    return json.loads((FIXTURES_DIR / adapter_name / filename).read_text())


def load_text_fixture(adapter_name: str, filename: str) -> str:
    return (FIXTURES_DIR / adapter_name / filename).read_text()
