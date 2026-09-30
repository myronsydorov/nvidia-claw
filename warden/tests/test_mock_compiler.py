import asyncio

import httpx2 as httpx
import pytest
from warden.app import app
from warden.compiler.mock import pick_template

AUTH = {"Authorization": "Bearer test-device-token"}


@pytest.fixture(autouse=True)
def mock_compiler_on(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUSTODY_COMPILER", "mock")
    monkeypatch.setenv("CUSTODY_MOCK_COMPILE_S", "0")


async def _wait_for_status(client: httpx.AsyncClient, worry_id: str, status: str) -> dict:  # type: ignore[type-arg]
    for _ in range(100):
        detail = (await client.get(f"/api/worries/{worry_id}", headers=AUTH)).json()
        if detail["worry"]["status"] == status:
            return detail  # type: ignore[no-any-return]
        await asyncio.sleep(0.01)
    raise AssertionError(f"worry never reached {status!r}: {detail['worry']['status']!r}")


async def test_hand_over_reaches_awaiting_approval_then_watching() -> None:
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
            assert [(p["method"], p["host"]) for p in watcher["policy_summary"]] == [
                ("GET", "api-eu.dhl.com")
            ]
            assert "*" not in watcher["policy_yaml"]
            assert "method: GET" in watcher["policy_yaml"]
            assert [e["kind"] for e in detail["timeline"]] == [
                "created",
                "triaged",
                "compiled",
                "approval_requested",
            ]

            approved = await client.post(f"/api/worries/{worry_id}/approve", headers=AUTH)
            assert approved.json()["worry"]["status"] == "watching"

        seen = []
        while not queue.empty():
            seen.append(queue.get_nowait().type)
        assert seen.count("approval.needed") == 1
        assert seen.count("worry.updated") >= 3


async def test_let_go_while_compiling_is_not_resurrected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CUSTODY_MOCK_COMPILE_S", "0.05")
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            worry_id = (
                await client.post("/api/worries", json={"text": "rain?"}, headers=AUTH)
            ).json()["id"]
            await client.post(f"/api/worries/{worry_id}/let-go", headers=AUTH)
            await asyncio.sleep(0.2)
            detail = (await client.get(f"/api/worries/{worry_id}", headers=AUTH)).json()
    assert detail["worry"]["status"] == "resolved"
    assert detail["watcher"] is None


def test_templates_are_picked_by_keyword() -> None:
    assert pick_template("storm on Saturday").adapter == "weather_openmeteo"
    assert pick_template("is my train cancelled").adapter == "transit_bvg"
    assert pick_template("my parcel").adapter == "parcel_dhl"


async def test_let_go_racing_the_compile_save_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    # Fire a let-go while the compile step is between its status check and its
    # save (inside the watcher write); the shared lock must make the let-go wait.
    monkeypatch.setenv("CUSTODY_MOCK_COMPILE_S", "0.01")
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
            for _ in range(100):
                if let_go:
                    break
                await asyncio.sleep(0.01)
            monkeypatch.setattr(store.watchers, "put", real_put)
            assert (await let_go[0]).status_code == 200
            detail = (await client.get(f"/api/worries/{worry_id}", headers=AUTH)).json()
    assert detail["worry"]["status"] == "resolved"
    assert detail["watcher"]["state"] == "retired"


def test_mock_compiler_refuses_real_sandboxes(monkeypatch: pytest.MonkeyPatch) -> None:
    from warden.compiler.mock import enabled

    monkeypatch.setenv("CUSTODY_SANDBOX", "openshell")
    with pytest.raises(RuntimeError, match="requires CUSTODY_SANDBOX=mock"):
        enabled()
    monkeypatch.delenv("CUSTODY_COMPILER")
    assert enabled() is False
