import pytest
from fastapi.testclient import TestClient
from warden.app import app


def test_missing_authorization_header_is_401() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health")
    assert response.status_code == 401


def test_wrong_token_is_401() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health", headers={"Authorization": "Bearer wrong-token"})
    assert response.status_code == 401


def test_non_bearer_scheme_is_401() -> None:
    with TestClient(app) as client:
        response = client.get("/api/health", headers={"Authorization": "Basic dGVzdA=="})
    assert response.status_code == 401


def test_unconfigured_server_token_rejects_everything(
    monkeypatch: pytest.MonkeyPatch, auth_headers: dict[str, str]
) -> None:
    monkeypatch.delenv("WARDEN_DEVICE_TOKEN", raising=False)
    with TestClient(app) as client:
        response = client.get("/api/health", headers=auth_headers)
    assert response.status_code == 401


def test_valid_token_is_accepted(auth_headers: dict[str, str]) -> None:
    with TestClient(app) as client:
        response = client.get("/api/health", headers=auth_headers)
    assert response.status_code == 200


def test_auth_applies_to_a_non_health_route_too(auth_headers: dict[str, str]) -> None:
    with TestClient(app) as client:
        without_token = client.post("/api/worries", json={"text": "x"})
        with_token = client.post("/api/worries", json={"text": "x"}, headers=auth_headers)
    assert without_token.status_code == 401
    assert with_token.status_code == 201
