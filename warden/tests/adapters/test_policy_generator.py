import pytest
import yaml
from warden.adapters.base import Adapter, Endpoint
from warden.compiler.policy import (
    WATCHER_BINARY,
    baseline_policy_yaml,
    egress_rules,
    generate_policy,
)
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
    return egress_rules(policy_yaml)


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


def test_policy_yaml_names_its_sandbox_in_a_header_comment() -> None:
    policy_yaml, _ = generate_policy([DHL], sandbox_name="cw-test8")
    assert policy_yaml.startswith("# Custody watcher policy for cw-test8:")


def test_policy_uses_the_openshell_schema_pinned_by_the_spike() -> None:
    doc = yaml.safe_load(generate_policy([DHL, WEATHER], sandbox_name="cw-test9")[0])
    assert doc["version"] == 1
    assert doc["landlock"] == {"compatibility": "strict"}
    assert doc["process"] == {"run_as_user": "sandbox", "run_as_group": "sandbox"}
    assert "/w" in doc["filesystem_policy"]["read_write"]
    assert doc["filesystem_policy"]["include_workdir"] is False
    assert len(doc["network_policies"]) == 2  # one entry per host:port
    for entry in doc["network_policies"].values():
        assert entry["binaries"] == [{"path": WATCHER_BINARY}]
        for endpoint in entry["endpoints"]:
            assert endpoint["protocol"] == "rest"  # L7: method and path are checked
            assert endpoint["enforcement"] == "enforce"
            assert "allow_encoded_slash" not in endpoint
            assert endpoint["rules"]
            assert all(r["allow"]["method"] == "GET" for r in endpoint["rules"])


def test_two_paths_on_one_host_share_one_entry() -> None:
    two = Adapter(
        name="two_paths",
        endpoints=[
            Endpoint(host="api.example.com", path="/a", why="a"),
            Endpoint(host="api.example.com", path="/b", why="b"),
        ],
        description="two paths on one host",
    )
    doc = yaml.safe_load(generate_policy([two], sandbox_name="cw-test10")[0])
    assert len(doc["network_policies"]) == 1
    assert egress_rules(yaml.safe_dump(doc)) == {
        ("api.example.com", 443, "GET", "/a"),
        ("api.example.com", 443, "GET", "/b"),
    }


def test_baseline_policy_allows_no_network() -> None:
    doc = yaml.safe_load(baseline_policy_yaml())
    assert doc["network_policies"] == {}
    assert egress_rules(baseline_policy_yaml()) == set()


def test_hosts_that_sanitize_alike_never_share_a_policy_entry() -> None:
    # T-04 security review: `a-b.example.com` and `a.b.example.com` once mapped to one key.
    both = Adapter(
        name="lookalikes",
        endpoints=[
            Endpoint(host="a-b.example.com", path="/one", why="one"),
            Endpoint(host="a.b.example.com", path="/two", why="two"),
        ],
        description="two hosts that sanitize to the same identifier",
    )
    policy_yaml, summary = generate_policy([both], sandbox_name="cw-test11")
    assert egress_rules(policy_yaml) == {
        ("a-b.example.com", 443, "GET", "/one"),
        ("a.b.example.com", 443, "GET", "/two"),
    }
    assert len(yaml.safe_load(policy_yaml)["network_policies"]) == 2
