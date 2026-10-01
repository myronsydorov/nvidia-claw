from fastapi.testclient import TestClient
from seed import seed_peer
from warden.app import app

PEER_ULID = "01K6B8Z3Q4R5S6T7V8W9XA0003"


def _peer() -> dict[str, object]:
    return {
        "id": f"p_{PEER_ULID}",
        "display_name": "Anna",
        "public_key": "QW5uYSdzIHB1YmxpYyBrZXksIDMyIGJ5dGVzIGxvbmc=",
        "paired_at": "2026-09-29T08:00:00Z",
    }


def test_list_people_requires_auth() -> None:
    with TestClient(app) as client:
        response = client.get("/api/people")
    assert response.status_code == 401


def test_list_people_empty_with_no_peers(auth_headers: dict[str, str]) -> None:
    with TestClient(app) as client:
        response = client.get("/api/people", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == []


def test_list_people_reflects_a_seeded_peer(
    auth_headers: dict[str, str], warden_test_environment: str
) -> None:
    seed_peer(warden_test_environment, _peer())
    with TestClient(app) as client:
        response = client.get("/api/people", headers=auth_headers)
    assert response.status_code == 200
    [item] = response.json()
    assert item["peer"]["display_name"] == "Anna"
    assert item["last_answer"] is None


def test_ask_unknown_peer_404s(auth_headers: dict[str, str]) -> None:
    with TestClient(app) as client:
        response = client.post(
            f"/api/people/p_{PEER_ULID}/ask", json={"q": "ok"}, headers=auth_headers
        )
    assert response.status_code == 404


def test_ask_without_a_relay_is_503_not_a_made_up_answer(
    auth_headers: dict[str, str], warden_test_environment: str
) -> None:
    seed_peer(warden_test_environment, _peer())
    with TestClient(app) as client:
        response = client.post(
            f"/api/people/p_{PEER_ULID}/ask", json={"q": "ok"}, headers=auth_headers
        )
        assert response.status_code == 503
        listed = client.get("/api/people", headers=auth_headers).json()
    assert listed[0]["last_answer"] is None


def test_ask_rejects_a_question_outside_the_fixed_vocabulary(
    auth_headers: dict[str, str], warden_test_environment: str
) -> None:
    seed_peer(warden_test_environment, _peer())
    with TestClient(app) as client:
        response = client.post(
            f"/api/people/p_{PEER_ULID}/ask", json={"q": "location"}, headers=auth_headers
        )
    assert response.status_code == 422
