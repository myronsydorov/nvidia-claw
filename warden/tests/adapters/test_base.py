import pytest
from pydantic import ValidationError
from warden.adapters.base import Adapter, Endpoint, parse_https_url


def _endpoint(**overrides: object) -> Endpoint:
    defaults: dict[str, object] = {
        "host": "api.example.com",
        "path": "/v1/status",
        "why": "check status",
    }
    defaults.update(overrides)
    return Endpoint.model_validate(defaults)


def test_endpoint_accepts_a_well_formed_declaration() -> None:
    endpoint = _endpoint()
    assert endpoint.host == "api.example.com"
    assert endpoint.port == 443
    assert endpoint.method == "GET"
    assert endpoint.path == "/v1/status"


@pytest.mark.parametrize(
    "host",
    ["*", "*.example.com", "api.example.com/*", "api.example.*", "", "api example.com"],
)
def test_endpoint_rejects_wildcard_or_malformed_hosts(host: str) -> None:
    with pytest.raises(ValidationError):
        _endpoint(host=host)


@pytest.mark.parametrize(
    "path",
    ["", "no-leading-slash", "/a/*", "/a/**", "/a?b=c", "/a b"],
)
def test_endpoint_rejects_wildcard_or_malformed_paths(path: str) -> None:
    with pytest.raises(ValidationError):
        _endpoint(path=path)


def test_endpoint_rejects_empty_why() -> None:
    with pytest.raises(ValidationError):
        _endpoint(why="")


def test_endpoint_method_is_get_only() -> None:
    with pytest.raises(ValidationError):
        _endpoint(method="POST")


@pytest.mark.parametrize("host", ["127.0.0.1", "169.254.169.254", "10.0.0.5", "192.168.1.1"])
def test_endpoint_rejects_bare_ip_literal_hosts_even_built_directly(host: str) -> None:
    """The SSRF guard must hold for Endpoint itself, not only for adapters that
    happen to go through parse_https_url() first."""
    with pytest.raises(ValidationError, match="IP literal"):
        _endpoint(host=host)


def test_adapter_requires_a_lowercase_snake_case_name() -> None:
    with pytest.raises(ValidationError):
        Adapter(
            name="Not-Valid!",
            endpoints=[_endpoint()],
            description="d",
        )


def test_adapter_accepts_a_well_formed_declaration() -> None:
    adapter = Adapter(
        name="http_json",
        endpoints=[_endpoint()],
        secrets=["EXAMPLE_KEY"],
        description="Fetch a JSON endpoint",
    )
    assert adapter.secrets == ["EXAMPLE_KEY"]


def test_parse_https_url_extracts_host_port_path() -> None:
    assert parse_https_url("https://example.com/a/b?x=1#frag") == ("example.com", 443, "/a/b")


def test_parse_https_url_defaults_empty_path_to_root() -> None:
    assert parse_https_url("https://example.com") == ("example.com", 443, "/")


def test_parse_https_url_honors_explicit_port() -> None:
    assert parse_https_url("https://example.com:8443/a") == ("example.com", 8443, "/a")


@pytest.mark.parametrize("url", ["http://example.com/a", "ftp://example.com/a"])
def test_parse_https_url_rejects_non_https_schemes(url: str) -> None:
    with pytest.raises(ValueError, match="https"):
        parse_https_url(url)


@pytest.mark.parametrize(
    "url",
    [
        "https://127.0.0.1/a",
        "https://169.254.169.254/latest/meta-data",
        "https://[::1]/a",
        "https://10.0.0.5/a",
    ],
)
def test_parse_https_url_rejects_bare_ip_literals(url: str) -> None:
    with pytest.raises(ValueError, match="IP literal"):
        parse_https_url(url)


def test_parse_https_url_rejects_missing_hostname() -> None:
    with pytest.raises(ValueError, match="hostname"):
        parse_https_url("https:///a")
