import pytest
from pydantic import ValidationError
from warden.adapters.base import Adapter, Endpoint, canonical_path, parse_https_url


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


def test_parse_https_url_refuses_a_non_standard_port() -> None:
    # T-04 security review: a worry-supplied URL may not pick a port (internal admin services).
    assert parse_https_url("https://example.com:443/a") == ("example.com", 443, "/a")
    with pytest.raises(ValueError):
        parse_https_url("https://example.com:8443/a")


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


# --- T-04: paths are declared in OpenShell's canonical form -------------------------------
# Measured on OpenShell 0.0.116 (ADR-0001 spike): the proxy decodes escapes of path-legal
# characters, keeps every other escape encoded, and compares the result literally against
# the rule. These cases mirror what it did.

_GCAL = (
    "https://calendar.google.com/calendar/ical/"
    "de.german%23holiday%40group.v.calendar.google.com/public/basic.ics"
)


def test_parse_https_url_canonicalizes_a_google_calendar_ics_link() -> None:
    host, port, path = parse_https_url(_GCAL)
    assert (host, port) == ("calendar.google.com", 443)
    # %40 -> '@' (OpenShell decodes it); %23 stays encoded (OpenShell keeps it).
    assert path == "/calendar/ical/de.german%23holiday@group.v.calendar.google.com/public/basic.ics"
    assert _endpoint(host=host, path=path).path == path


@pytest.mark.parametrize(
    ("raw", "canonical"),
    [
        ("/v1/forecast", "/v1/forecast"),
        ("/v1/a%40b", "/v1/a@b"),
        ("/v1/e%2bf", "/v1/e+f"),
        ("/v1/g%3ah", "/v1/g:h"),
        ("/v1/t%7el", "/v1/t~l"),
        ("/v1/%46orecast", "/v1/Forecast"),
        ("/v1/c%23d", "/v1/c%23d"),
        ("/v1/sp%20ace", "/v1/sp%20ace"),
        ("/v1/pct%25x", "/v1/pct%25x"),
        ("/v1/q%3fx", "/v1/q%3Fx"),
        ("/stra%c3%9fe", "/stra%C3%9Fe"),
        ("/straße", "/stra%C3%9Fe"),
        ("/v1/forecast/", "/v1/forecast/"),
        ("/", "/"),
    ],
)
def test_canonical_path_matches_openshell(raw: str, canonical: str) -> None:
    assert canonical_path(raw) == canonical


@pytest.mark.parametrize(
    "raw",
    [
        "/a%2Fb",  # encoded slash: OpenShell refuses it (allow_encoded_slash is never set)
        "/a%2fb",
        "/a%5C..%5Cb",  # encoded backslash: some servers treat it as a separator
        "/a%00",  # control bytes
        "/a%0a",
        "/a%7F",
        "/a%zz",  # malformed escapes
        "/a%4",
        "/a/*",  # a glob
        "/a%2Ab",  # decodes to a glob
        "/a;b",  # a path parameter OpenShell strips before matching
        "/a%3Bb",
        "/a/../b",  # dot segments OpenShell would resolve
        "/a/%2e%2e/b",
        "/./a",
        "//a",  # empty segments OpenShell would merge
        "/a//b",
        "/a b",
        "/a!b",
        "/a(b)",
        "no-slash",
    ],
)
def test_canonical_path_refuses_what_cannot_be_declared_safely(raw: str) -> None:
    with pytest.raises(ValueError):
        canonical_path(raw)


@pytest.mark.parametrize("path", ["/v1/a%40b", "/v1/e%2Bf", "/v1/q%3fx"])
def test_endpoint_rejects_a_non_canonical_path(path: str) -> None:
    # As a rule, '/v1/a%40b' never matches anything: OpenShell compares against '/v1/a@b'.
    # Kept escapes are written with upper-case hex ('%3F', not '%3f').
    with pytest.raises(ValidationError):
        _endpoint(path=path)


def test_endpoint_accepts_a_kept_escape() -> None:
    assert _endpoint(path="/v1/c%23d").path == "/v1/c%23d"
