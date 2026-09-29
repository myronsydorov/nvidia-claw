from fastapi.testclient import TestClient
from warden.app import app

SUBSCRIPTION = {
    "endpoint": "https://push.example/abc",
    "keys": {"p256dh": "x", "auth": "y"},
}


def test_push_subscribe_requires_auth() -> None:
    with TestClient(app) as client:
        response = client.post("/api/push/subscribe", json=SUBSCRIPTION)
    assert response.status_code == 401


def test_push_subscribe_persists(auth_headers: dict[str, str]) -> None:
    with TestClient(app) as client:
        response = client.post("/api/push/subscribe", json=SUBSCRIPTION, headers=auth_headers)
    assert response.status_code == 204


def test_push_subscribe_rejects_a_malformed_body(auth_headers: dict[str, str]) -> None:
    with TestClient(app) as client:
        response = client.post("/api/push/subscribe", json={"endpoint": "x"}, headers=auth_headers)
    assert response.status_code == 422
