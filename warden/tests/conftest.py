import tempfile
from collections.abc import Iterator

import pytest
from l2_harness import fast_pairing_kdf, pair  # noqa: F401  (L2 fixtures)


@pytest.fixture(autouse=True)
def warden_test_environment(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Isolated env + a fresh temp SQLite file for every test.

    A plain sync sqlite3 connection (see seed.py) can pre-populate that file
    before the app's own aiosqlite connection opens it in TestClient's lifespan
    startup, without the two connections ever sharing an event loop.
    """
    monkeypatch.setenv("CUSTODY_SANDBOX", "mock")
    monkeypatch.setenv("WARDEN_DEVICE_TOKEN", "test-device-token")
    monkeypatch.setenv("WARDEN_SCHEDULER", "off")  # route tests drive state; no background ticks
    monkeypatch.setenv("WARDEN_COMPILER", "off")  # ...and no background compiles
    monkeypatch.delenv("CUSTODY_LLM_REPLAY", raising=False)
    monkeypatch.delenv("NVIDIA_API_KEY", raising=False)  # never a live model call from a test
    monkeypatch.delenv("RELAY_URL", raising=False)  # no relay unless a test brings its own
    monkeypatch.delenv("CUSTODY_CALENDAR_ICS", raising=False)
    monkeypatch.setenv("CUSTODY_ACTIVITY", "off")  # never read this machine's idle time

    async def public_only(host: str, port: int) -> list[str]:
        return ["93.184.215.14"]  # no live DNS in unit tests; every host looks public

    monkeypatch.setattr("warden.compiler.hosts.resolve", public_only)

    async def no_bvg(path: str, params: dict[str, str]) -> list[object]:
        return []  # no live BVG lookups in unit tests; tests that need one bring a fixture

    monkeypatch.setattr("warden.adapters.bvg_lookup.fetch", no_bvg)
    with tempfile.TemporaryDirectory() as tmp:
        db_path = f"{tmp}/warden-test.db"
        monkeypatch.setenv("WARDEN_DB_PATH", db_path)
        monkeypatch.setenv("WARDEN_KEY_PATH", f"{tmp}/warden-test.key")
        yield db_path


@pytest.fixture
def auth_headers() -> dict[str, str]:
    return {"Authorization": "Bearer test-device-token"}
