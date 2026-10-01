import pytest
from fastapi.testclient import TestClient
from seed import seed_watcher, seed_worry
from warden.app import app

WORRY_ULID = "01K6B8Z3Q4R5S6T7V8W9XA0001"
WATCHER_ULID = "01K6B8Z3Q4R5S6T7V8W9XA0002"


def _watcher(worry_id: str, state: str) -> dict[str, object]:
    return {
        "id": f"wt_{WATCHER_ULID}",
        "worry_id": worry_id,
        "adapters": ["parcel_dhl"],
        "code": "",
        "policy_yaml": "network_policies: {}\n",
        "policy_summary": [
            {"method": "GET", "host": "api-eu.dhl.com", "path": "/track/shipments", "why": "x"}
        ],
        "sandbox_name": "cw-xa0001",
        "interval_s": 3600,
        "state": state,
        "last_result": None,
    }


def _worry(status: str, watcher_id: str | None) -> dict[str, object]:
    return {
        "id": f"w_{WORRY_ULID}",
        "text": "I'm worried my parcel won't arrive before Friday",
        "type": "deadline",
        "fear": "Parcel not delivered by Friday 18:00",
        "deadline": "2026-10-02T16:00:00Z",
        "status": status,
        "watcher_id": watcher_id,
        "resolution": None,
        "fear_came_true": None,
        "created_at": "2026-09-29T08:00:00Z",
        "updated_at": "2026-09-29T08:00:00Z",
    }


def test_create_worry_requires_auth() -> None:
    with TestClient(app) as client:
        response = client.post("/api/worries", json={"text": "x"})
    assert response.status_code == 401


def test_create_worry_persists_as_triaging(auth_headers: dict[str, str]) -> None:
    with TestClient(app) as client:
        response = client.post("/api/worries", json={"text": "My parcel"}, headers=auth_headers)
        assert response.status_code == 201
        worry = response.json()
        assert worry["status"] == "triaging"
        assert worry["type"] == "unclassified"
        assert worry["watcher_id"] is None

        detail = client.get(f"/api/worries/{worry['id']}", headers=auth_headers).json()
        assert detail["worry"]["id"] == worry["id"]
        assert detail["watcher"] is None
        assert [e["kind"] for e in detail["timeline"]] == ["created"]


def test_get_worry_404_for_unknown_id(auth_headers: dict[str, str]) -> None:
    with TestClient(app) as client:
        response = client.get("/api/worries/w_01K6B8Z3Q4R5S6T7V8W9XA9999", headers=auth_headers)
    assert response.status_code == 404


def test_list_worries_filters_by_status(
    auth_headers: dict[str, str], warden_test_environment: str
) -> None:
    with TestClient(app) as client:
        client.post("/api/worries", json={"text": "x"}, headers=auth_headers)

        triaging = client.get("/api/worries?status=triaging", headers=auth_headers).json()
        assert len(triaging) == 1
        assert triaging[0]["worry"]["status"] == "triaging"

        resolved = client.get("/api/worries?status=resolved", headers=auth_headers).json()
        assert resolved == []


def test_approve_requires_a_watcher_awaiting_approval(auth_headers: dict[str, str]) -> None:
    with TestClient(app) as client:
        created = client.post("/api/worries", json={"text": "x"}, headers=auth_headers).json()
        response = client.post(f"/api/worries/{created['id']}/approve", headers=auth_headers)
    assert response.status_code == 409


def test_approve_activates_watcher_and_worry(
    auth_headers: dict[str, str], warden_test_environment: str
) -> None:
    db_path = warden_test_environment
    watcher_id = f"wt_{WATCHER_ULID}"
    worry_id = f"w_{WORRY_ULID}"
    seed_worry(db_path, _worry("awaiting_approval", watcher_id), timeline=[])
    seed_watcher(db_path, _watcher(worry_id, "awaiting_approval"))

    with TestClient(app) as client:
        response = client.post(f"/api/worries/{worry_id}/approve", headers=auth_headers)
        assert response.status_code == 200
        detail = response.json()
        assert detail["worry"]["status"] == "watching"
        assert detail["watcher"]["state"] == "active"
        assert detail["timeline"][-1]["kind"] == "approved"

        health = client.get("/api/health", headers=auth_headers).json()
        assert health["sandboxes_live"] == 1


def test_deny_parks_worry_and_retires_watcher(
    auth_headers: dict[str, str], warden_test_environment: str
) -> None:
    db_path = warden_test_environment
    watcher_id = f"wt_{WATCHER_ULID}"
    worry_id = f"w_{WORRY_ULID}"
    seed_worry(db_path, _worry("awaiting_approval", watcher_id), timeline=[])
    seed_watcher(db_path, _watcher(worry_id, "awaiting_approval"))

    with TestClient(app) as client:
        response = client.post(f"/api/worries/{worry_id}/deny", headers=auth_headers)
        assert response.status_code == 200
        detail = response.json()
        assert detail["worry"]["status"] == "parked"
        assert detail["watcher"]["state"] == "retired"
        assert detail["timeline"][-1]["kind"] == "denied"


def test_let_go_resolves_a_bare_worry(auth_headers: dict[str, str]) -> None:
    with TestClient(app) as client:
        created = client.post("/api/worries", json={"text": "x"}, headers=auth_headers).json()
        response = client.post(f"/api/worries/{created['id']}/let-go", headers=auth_headers)
    assert response.status_code == 200
    detail = response.json()
    assert detail["worry"]["status"] == "resolved"
    assert detail["timeline"][-1]["kind"] == "let_go"


def test_let_go_retires_an_already_active_watcher_even_if_the_driver_lost_it(
    auth_headers: dict[str, str], warden_test_environment: str
) -> None:
    # Seeded directly as "active" (bypassing approve), so the in-memory MockDriver
    # never actually created this sandbox_name -- exercises the KeyError-tolerant path.
    db_path = warden_test_environment
    watcher_id = f"wt_{WATCHER_ULID}"
    worry_id = f"w_{WORRY_ULID}"
    seed_worry(db_path, _worry("watching", watcher_id), timeline=[])
    seed_watcher(db_path, _watcher(worry_id, "active"))

    with TestClient(app) as client:
        response = client.post(f"/api/worries/{worry_id}/let-go", headers=auth_headers)
        assert response.status_code == 200
        detail = response.json()
        assert detail["worry"]["status"] == "resolved"
        assert detail["watcher"]["state"] == "retired"


def test_outcome_requires_a_resolved_worry(auth_headers: dict[str, str]) -> None:
    with TestClient(app) as client:
        created = client.post("/api/worries", json={"text": "x"}, headers=auth_headers).json()
        response = client.post(
            f"/api/worries/{created['id']}/outcome",
            json={"fear_came_true": False},
            headers=auth_headers,
        )
    assert response.status_code == 409


def test_outcome_records_fear_came_true(auth_headers: dict[str, str]) -> None:
    with TestClient(app) as client:
        created = client.post("/api/worries", json={"text": "x"}, headers=auth_headers).json()
        client.post(f"/api/worries/{created['id']}/let-go", headers=auth_headers)
        response = client.post(
            f"/api/worries/{created['id']}/outcome",
            json={"fear_came_true": True},
            headers=auth_headers,
        )
    assert response.status_code == 200
    assert response.json()["worry"]["fear_came_true"] is True


def test_approve_refuses_a_host_that_now_resolves_privately(
    auth_headers: dict[str, str], warden_test_environment: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    # T-04 security review: DNS is checked again at approve, before any sandbox exists.
    from warden.adapters.parcel_dhl import ADAPTER
    from warden.compiler.policy import generate_policy

    async def private(host: str, port: int) -> list[str]:
        return ["10.0.0.7"]

    monkeypatch.setattr("warden.compiler.hosts.resolve", private)
    db_path = warden_test_environment
    watcher_id = f"wt_{WATCHER_ULID}"
    worry_id = f"w_{WORRY_ULID}"
    seed_worry(db_path, _worry("awaiting_approval", watcher_id), timeline=[])
    watcher = _watcher(worry_id, "awaiting_approval")
    watcher["policy_yaml"] = generate_policy([ADAPTER], str(watcher["sandbox_name"]))[0]
    seed_watcher(db_path, watcher)

    with TestClient(app) as client:
        response = client.post(f"/api/worries/{worry_id}/approve", headers=auth_headers)
        assert response.status_code == 409
        assert "private or local" in response.json()["detail"]
        health = client.get("/api/health", headers=auth_headers).json()
        assert health["sandboxes_live"] == 0
