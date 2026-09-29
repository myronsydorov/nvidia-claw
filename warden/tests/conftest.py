import tempfile
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def warden_test_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Isolated env + a fresh temp SQLite file for every test.

    A plain sync sqlite3 connection (see seed.py) can pre-populate that file
    before the app's own aiosqlite connection opens it in TestClient's lifespan
    startup, without the two connections ever sharing an event loop.
    """
    monkeypatch.setenv("CUSTODY_SANDBOX", "mock")
    monkeypatch.setenv("WARDEN_DEVICE_TOKEN", "test-device-token")
    with tempfile.TemporaryDirectory() as tmp:
        db_path = f"{tmp}/warden-test.db"
        monkeypatch.setenv("WARDEN_DB_PATH", db_path)
        yield db_path


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-device-token"}
