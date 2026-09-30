import asyncio

import pytest
from warden.sandbox.factory import get_sandbox_driver
from warden.sandbox.mock import MockDriver


def test_mock_driver_lifecycle() -> None:
    async def run() -> None:
        driver = MockDriver()
        handle = await driver.create("cw-test", image="watcher-base")
        assert handle.name == "cw-test"

        await driver.apply_policy("cw-test", "network_policies: {}")

        result = await driver.exec("cw-test", ["python3", "/w/run.py"])
        assert result.exit_code == 0

        await driver.delete("cw-test")

        with pytest.raises(KeyError):
            await driver.exec("cw-test", ["python3", "/w/run.py"])

    asyncio.run(run())


def test_factory_returns_mock_driver_when_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUSTODY_SANDBOX", "mock")
    assert isinstance(get_sandbox_driver(), MockDriver)


def test_factory_raises_for_unconfigured_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("CUSTODY_SANDBOX", raising=False)
    with pytest.raises(NotImplementedError):
        get_sandbox_driver()


def test_mock_driver_write_file_keeps_code_in_memory() -> None:
    async def run() -> None:
        driver = MockDriver()
        await driver.create("cw-files", image="watcher-base")
        await driver.write_file("cw-files", "/w/run.py", "print('hi')\n")
        assert driver.file("cw-files", "/w/run.py") == "print('hi')\n"
        await driver.delete("cw-files")
        assert driver.file("cw-files", "/w/run.py") is None
        with pytest.raises(KeyError):
            await driver.write_file("cw-files", "/w/run.py", "x")

    asyncio.run(run())
