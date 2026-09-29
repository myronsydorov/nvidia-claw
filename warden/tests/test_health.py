from fastapi.testclient import TestClient
from warden.app import app


def test_health_ok(auth_headers: dict[str, str]) -> None:
    with TestClient(app) as client:
        response = client.get("/api/health", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "sandboxes_live": 0}


def test_health_requires_auth() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 401
