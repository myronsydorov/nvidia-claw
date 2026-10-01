from fastapi.testclient import TestClient
from warden.app import app


def test_ledger_requires_auth() -> None:
    with TestClient(app) as client:
        response = client.get("/api/ledger")
    assert response.status_code == 401


def test_ledger_starts_at_zero(auth_headers: dict[str, str]) -> None:
    with TestClient(app) as client:
        response = client.get("/api/ledger", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert body["worries_total"] == 0
    assert body["sandboxes_live"] == 0
    assert body["locations_shared"] == 0
    assert body["came_true_rate"] == 0.0  # no known outcome yet


def test_ledger_counts_worries_and_outcomes(auth_headers: dict[str, str]) -> None:
    with TestClient(app) as client:
        a = client.post("/api/worries", json={"text": "a"}, headers=auth_headers).json()
        b = client.post("/api/worries", json={"text": "b"}, headers=auth_headers).json()

        client.post(f"/api/worries/{a['id']}/let-go", headers=auth_headers)
        client.post(
            f"/api/worries/{a['id']}/outcome", json={"fear_came_true": True}, headers=auth_headers
        )
        client.post(f"/api/worries/{b['id']}/let-go", headers=auth_headers)
        client.post(
            f"/api/worries/{b['id']}/outcome", json={"fear_came_true": False}, headers=auth_headers
        )

        response = client.get("/api/ledger", headers=auth_headers)
    body = response.json()
    assert body["worries_total"] == 2
    assert body["needed_you"] == 1
    assert body["never_needed_you"] == 1
    # CONTRACTS §5: came true / closed with a known outcome, as a 0–1 fraction.
    assert body["came_true_rate"] == 0.5
