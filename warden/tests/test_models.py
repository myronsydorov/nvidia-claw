import pytest
from pydantic import ValidationError
from warden.models import Watcher, WorryDetail

ULID = "01K6B8Z3Q4R5S6T7V8W9XA0001"

PERMISSION = {
    "method": "GET",
    "host": "api-eu.dhl.com",
    "path": "/track/shipments",
    "why": "check the parcel's status",
}

WATCHER: dict[str, object] = {
    "id": f"wt_{ULID}",
    "worry_id": f"w_{ULID}",
    "adapters": ["parcel_dhl"],
    "code": "",
    "policy_yaml": "",
    "policy_summary": [PERMISSION],
    "sandbox_name": "cw-xa0001",
    "interval_s": 3600,
    "state": "active",
    "last_result": None,
}


def test_worry_detail_accepts_contract_shape() -> None:
    detail = WorryDetail.model_validate(
        {
            "worry": {
                "id": f"w_{ULID}",
                "text": "I'm worried my parcel won't arrive before Friday",
                "type": "deadline",
                "fear": "Parcel not delivered by Friday 18:00",
                "deadline": "2026-10-02T16:00:00Z",
                "status": "watching",
                "watcher_id": f"wt_{ULID}",
                "resolution": None,
                "fear_came_true": None,
                "created_at": "2026-09-29T08:00:00Z",
                "updated_at": "2026-09-29T09:00:00Z",
            },
            "watcher": WATCHER,
            "timeline": [
                {"at": "2026-09-29T08:00:00Z", "kind": "created", "text": "You handed it over."}
            ],
        }
    )
    assert detail.watcher is not None
    assert detail.watcher.policy_summary[0].host == "api-eu.dhl.com"


@pytest.mark.parametrize(
    "change",
    [
        {"sandbox_name": "cw-abcdefghijklmnopq"},  # 20 chars
        {"interval_s": 299},
        {"policy_summary": [{**PERMISSION, "method": "POST"}]},
        {"id": ULID},
    ],
)
def test_watcher_rejects_out_of_contract(change: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        Watcher.model_validate({**WATCHER, **change})
