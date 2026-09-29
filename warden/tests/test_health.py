from fastapi.testclient import TestClient
from warden.app import app


def test_health_ok() -> None:
    client = TestClient(app)
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok", "sandboxes_live": 0}
