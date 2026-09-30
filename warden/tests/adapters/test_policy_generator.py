import pytest
import yaml
from warden.adapters.base import Adapter, Endpoint
from warden.compiler.policy import generate_policy
from warden.models import PermissionLine

DHL = Adapter(
    name="parcel_dhl",
    endpoints=[Endpoint(host="api-eu.dhl.com", path="/track/shipments", why="check parcel status")],
    secrets=["DHL_API_KEY"],
    description="Track a DHL shipment",
)
WEATHER = Adapter(
    name="weather_openmeteo",
    endpoints=[Endpoint(host="api.open-meteo.com", path="/v1/forecast", why="check forecast")],
    description="Check the weather forecast",
)


def _egress_tuples(policy_yaml: str) -> set[tuple[str, int, str, str]]:
    doc = yaml.safe_load(policy_yaml)
    return {(e["host"], e["port"], e["method"], e["path"]) for e in doc["egress"]}


def test_generates_one_egress_rule_per_endpoint() -> None:
    policy_yaml, summary = generate_policy([DHL], sandbox_name="cw-test1")
    assert _egress_tuples(policy_yaml) == {("api-eu.dhl.com", 443, "GET", "/track/shipments")}
    assert summary == [
        PermissionLine(
            method="GET", host="api-eu.dhl.com", path="/track/shipments", why="check parcel status"
        )
    ]


def test_multiple_adapters_produce_the_union_of_endpoints() -> None:
    policy_yaml, summary = generate_policy([DHL, WEATHER], sandbox_name="cw-test2")
    assert _egress_tuples(policy_yaml) == {
        ("api-eu.dhl.com", 443, "GET", "/track/shipments"),
        ("api.open-meteo.com", 443, "GET", "/v1/forecast"),
    }
    assert len(summary) == 2


def test_identical_endpoint_declared_twice_is_deduped() -> None:
    duplicate = Adapter(
        name="parcel_dhl_dup",
        endpoints=[
            Endpoint(host="api-eu.dhl.com", path="/track/shipments", why="check parcel status")
        ],
        description="duplicate declaration of the same endpoint",
    )
    policy_yaml, summary = generate_policy([DHL, duplicate], sandbox_name="cw-test3")
    assert _egress_tuples(policy_yaml) == {("api-eu.dhl.com", 443, "GET", "/track/shipments")}
    assert len(summary) == 1


def test_conflicting_why_for_the_same_endpoint_raises() -> None:
    conflicting = Adapter(
        name="parcel_dhl_conflict",
        endpoints=[
            Endpoint(host="api-eu.dhl.com", path="/track/shipments", why="a different reason")
        ],
        description="conflicting why for the same endpoint",
    )
    with pytest.raises(ValueError, match="conflicting"):
        generate_policy([DHL, conflicting], sandbox_name="cw-test4")


def test_undeclared_adapter_host_is_absent_from_the_generated_policy() -> None:
    policy_yaml, _ = generate_policy([DHL], sandbox_name="cw-test5")
    assert WEATHER.endpoints[0].host not in policy_yaml


def test_no_wildcards_in_generated_yaml() -> None:
    policy_yaml, _ = generate_policy([DHL, WEATHER], sandbox_name="cw-test6")
    assert "*" not in policy_yaml
    assert "?" not in policy_yaml


def test_round_trips_through_yaml_with_no_widening_or_dropped_rules() -> None:
    adapters = [DHL, WEATHER]
    policy_yaml, _ = generate_policy(adapters, sandbox_name="cw-test7")
    expected = {(e.host, e.port, e.method, e.path) for a in adapters for e in a.endpoints}
    assert _egress_tuples(policy_yaml) == expected


def test_policy_yaml_includes_a_provisional_schema_header() -> None:
    policy_yaml, _ = generate_policy([DHL], sandbox_name="cw-test8")
    assert policy_yaml.startswith("# provisional policy schema")
