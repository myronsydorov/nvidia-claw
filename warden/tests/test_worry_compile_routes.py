"""Hand-over through the real routes and compiler (replayed model answers, mock sandboxes)."""

import asyncio
from pathlib import Path

import httpx2 as httpx
import pytest
from warden.app import app
from warden.sandbox.mock import MockDriver

AUTH = {"Authorization": "Bearer test-device-token"}
REPLAY = Path(__file__).parent / "fixtures" / "llm" / "replay.json"


@pytest.fixture(autouse=True)
def compiler_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("WARDEN_COMPILER")
    monkeypatch.setenv("CUSTODY_LLM_REPLAY", str(REPLAY))


async def _wait_for_status(client: httpx.AsyncClient, worry_id: str, status: str) -> dict:  # type: ignore[type-arg]
    for _ in range(200):
        detail = (await client.get(f"/api/worries/{worry_id}", headers=AUTH)).json()
        if detail["worry"]["status"] == status:
            return detail  # type: ignore[no-any-return]
        await asyncio.sleep(0.01)
    raise AssertionError(f"worry never reached {status!r}: {detail['worry']['status']!r}")


async def test_hand_over_compiles_then_approve_puts_run_py_in_the_sandbox() -> None:
    async with app.router.lifespan_context(app):
        queue = app.state.events.subscribe()
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            created = await client.post(
                "/api/worries", json={"text": "Will my DHL parcel arrive?"}, headers=AUTH
            )
            worry_id = created.json()["id"]
            assert created.json()["status"] == "triaging"

            detail = await _wait_for_status(client, worry_id, "awaiting_approval")
            watcher = detail["watcher"]
            assert watcher["state"] == "awaiting_approval"
            assert watcher["adapters"] == ["parcel_dhl"]
            assert [(p["method"], p["host"], p["path"]) for p in watcher["policy_summary"]] == [
                ("GET", "api-eu.dhl.com", "/track/shipments")
            ]
            assert "*" not in watcher["policy_yaml"]
            assert [e["kind"] for e in detail["timeline"]] == [
                "created",
                "triaged",
                "compiled",
                "approval_requested",
            ]

            approved = await client.post(f"/api/worries/{worry_id}/approve", headers=AUTH)
            assert approved.json()["worry"]["status"] == "watching"
            driver: MockDriver = app.state.driver
            assert driver.file(watcher["sandbox_name"], "/w/run.py") == watcher["code"]

        seen = []
        while not queue.empty():
            seen.append(queue.get_nowait().type)
        assert seen.count("approval.needed") == 1


async def test_a_person_worry_is_parked_with_a_reason() -> None:
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            worry_id = (
                await client.post("/api/worries", json={"text": "Is my mum OK?"}, headers=AUTH)
            ).json()["id"]
            detail = await _wait_for_status(client, worry_id, "parked")
    assert detail["worry"]["type"] == "person"
    assert detail["worry"]["resolution"]
    assert detail["watcher"] is None


async def test_let_go_racing_the_compile_save_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    # Fire a let-go while the compiler is between its status check and its save
    # (inside the watcher write); the shared lock must make the let-go wait.
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            store = app.state.store
            real_put = store.watchers.put
            let_go: list[asyncio.Task[httpx.Response]] = []

            async def put_then_race(*args: object, **kwargs: str) -> None:
                let_go.append(
                    asyncio.create_task(
                        client.post(f"/api/worries/{worry_id}/let-go", headers=AUTH)
                    )
                )
                await asyncio.sleep(0.05)  # give the let-go every chance to interleave
                await real_put(*args, **kwargs)

            monkeypatch.setattr(store.watchers, "put", put_then_race)
            worry_id = (
                await client.post("/api/worries", json={"text": "my parcel"}, headers=AUTH)
            ).json()["id"]
            for _ in range(200):
                if let_go:
                    break
                await asyncio.sleep(0.01)
            monkeypatch.setattr(store.watchers, "put", real_put)
            assert (await let_go[0]).status_code == 200
            detail = (await client.get(f"/api/worries/{worry_id}", headers=AUTH)).json()
    assert detail["worry"]["status"] == "resolved"
    assert detail["watcher"]["state"] == "retired"


async def test_a_failed_approve_leaves_no_sandbox_behind(monkeypatch: pytest.MonkeyPatch) -> None:
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            worry_id = (
                await client.post("/api/worries", json={"text": "my parcel"}, headers=AUTH)
            ).json()["id"]
            detail = await _wait_for_status(client, worry_id, "awaiting_approval")
            driver: MockDriver = app.state.driver

            async def broken_write(name: str, path: str, content: str) -> None:
                raise OSError("disk full")

            monkeypatch.setattr(driver, "write_file", broken_write)
            with pytest.raises(OSError):
                await client.post(f"/api/worries/{worry_id}/approve", headers=AUTH)
            assert driver.file(detail["watcher"]["sandbox_name"], "/w/run.py") is None
            with pytest.raises(KeyError):  # the half-built sandbox was deleted
                await driver.exec(detail["watcher"]["sandbox_name"], ["true"])
            after = (await client.get(f"/api/worries/{worry_id}", headers=AUTH)).json()
    assert after["worry"]["status"] == "awaiting_approval"
