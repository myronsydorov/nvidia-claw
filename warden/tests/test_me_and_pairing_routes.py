from fastapi.testclient import TestClient
from warden.app import app


def test_me_routes_require_auth() -> None:
    with TestClient(app) as client:
        assert client.get("/api/me/signal").status_code == 401
        assert client.post("/api/me/check-in").status_code == 401
        assert client.post("/api/me/help").status_code == 401
        assert client.post("/api/pairing", json={"display_name": "Anna"}).status_code == 401


def test_signal_follows_check_in_and_help(auth_headers: dict[str, str]) -> None:
    with TestClient(app) as client:
        signal = client.get("/api/me/signal", headers=auth_headers).json()
        assert (signal["level"], signal["reason"]) == ("unknown", "not_enough_data")

        assert client.post("/api/me/check-in", headers=auth_headers).status_code == 204
        signal = client.get("/api/me/signal", headers=auth_headers).json()
        assert (signal["level"], signal["reason"]) == ("normal", "active_as_usual")

        assert client.post("/api/me/help", headers=auth_headers).status_code == 204
        signal = client.get("/api/me/signal", headers=auth_headers).json()
        assert (signal["level"], signal["reason"]) == ("help", "asked_for_help")
        assert set(signal) == {"level", "reason", "ts"}

        assert client.delete("/api/me/help", headers=auth_headers).status_code == 204
        signal = client.get("/api/me/signal", headers=auth_headers).json()
        assert signal["level"] == "normal"  # the check-in is still fresh


def test_a_check_in_clears_help(auth_headers: dict[str, str]) -> None:
    with TestClient(app) as client:
        client.post("/api/me/help", headers=auth_headers)
        client.post("/api/me/check-in", headers=auth_headers)
        assert client.get("/api/me/signal", headers=auth_headers).json()["level"] == "normal"


def test_pairing_without_a_relay_is_503(auth_headers: dict[str, str]) -> None:
    with TestClient(app) as client:
        start = client.post("/api/pairing", json={"display_name": "Anna"}, headers=auth_headers)
        join = client.post(
            "/api/pairing/join",
            json={"code": "ABCDEFGH", "display_name": "Anna"},
            headers=auth_headers,
        )
    assert start.status_code == 503
    assert join.status_code == 503


def test_a_malformed_code_is_422(auth_headers: dict[str, str]) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/pairing/join",
            json={"code": "ABCD-EFGU", "display_name": "Anna"},
            headers=auth_headers,
        )
    assert response.status_code == 422


def test_display_name_is_bounded(auth_headers: dict[str, str]) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/api/pairing", json={"display_name": "x" * 65}, headers=auth_headers
        )
    assert response.status_code == 422
