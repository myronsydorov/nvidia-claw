from fastapi.testclient import TestClient
from warden.app import app

PEER_ULID = "01K6B8Z3Q4R5S6T7V8W9XA0003"


def test_get_sharing_rules_requires_auth() -> None:
    with TestClient(app) as client:
        response = client.get("/api/sharing-rules")
    assert response.status_code == 401


def test_get_sharing_rules_starts_empty(auth_headers: dict[str, str]) -> None:
    with TestClient(app) as client:
        response = client.get("/api/sharing-rules", headers=auth_headers)
    assert response.status_code == 200
    assert response.json() == {"rules": [], "questions_log": []}


def test_put_sharing_rules_replaces_the_rule_set(auth_headers: dict[str, str]) -> None:
    rule = {
        "peer_id": f"p_{PEER_ULID}",
        "allowed_questions": ["ok"],
        "allowed_levels": ["normal", "unusual"],
        "active": True,
    }
    with TestClient(app) as client:
        put_response = client.put(
            "/api/sharing-rules",
            json={"rules": [rule], "questions_log": []},
            headers=auth_headers,
        )
        assert put_response.status_code == 200
        assert put_response.json()["rules"] == [rule]

        get_response = client.get("/api/sharing-rules", headers=auth_headers)
        assert get_response.json()["rules"] == [rule]

        # A second PUT with an empty list clears it.
        cleared = client.put(
            "/api/sharing-rules", json={"rules": [], "questions_log": []}, headers=auth_headers
        )
    assert cleared.json()["rules"] == []


def test_put_sharing_rules_ignores_a_client_supplied_questions_log(
    auth_headers: dict[str, str],
) -> None:
    # questions_log is server-maintained; nothing populates it in T-07 (no relay yet).
    forged_entry = {
        "id": "q1",
        "peer_id": f"p_{PEER_ULID}",
        "question": "ok",
        "asked_at": "2026-09-29T08:00:00Z",
        "answer_level": "normal",
    }
    with TestClient(app) as client:
        response = client.put(
            "/api/sharing-rules",
            json={"rules": [], "questions_log": [forged_entry]},
            headers=auth_headers,
        )
    assert response.json()["questions_log"] == []


def test_put_sharing_rules_rejects_a_level_outside_the_fixed_vocabulary(
    auth_headers: dict[str, str],
) -> None:
    bad_rule = {
        "peer_id": f"p_{PEER_ULID}",
        "allowed_questions": ["ok"],
        "allowed_levels": ["fine"],
        "active": True,
    }
    with TestClient(app) as client:
        response = client.put(
            "/api/sharing-rules",
            json={"rules": [bad_rule], "questions_log": []},
            headers=auth_headers,
        )
    assert response.status_code == 422
