"""AdapterDeclaration shapes (docs/CONTRACTS.md §1) and a shared URL-parsing guard.

`Endpoint`/`Adapter` are compiler-internal: they describe what a watcher may call
over the network and feed the policy generator (warden.compiler.policy). They are
never serialized to /api, so they do not belong in warden.models (which mirrors the
public contract + app/src/api/schemas.ts).

Every declared path is an exact literal path, never a prefix or wildcard — dynamic
identifiers belong in the query string, or get baked into one exact path string at
declare-time (see warden.adapters.transit_bvg). AGENTS.md invariant #2: no wildcard
hosts, no hand-widening, GET-only unless an ADR says otherwise.
"""

import ipaddress
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

_HOST_PATTERN = r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$"
_PATH_PATTERN = r"^/[A-Za-z0-9_./-]*$"
_NAME_PATTERN = r"^[a-z][a-z0-9_]*$"


class Endpoint(BaseModel):
    host: str = Field(pattern=_HOST_PATTERN)
    port: int = Field(default=443, ge=1, le=65535)
    method: Literal["GET"] = "GET"
    path: str = Field(pattern=_PATH_PATTERN)
    why: str = Field(min_length=1)

    @field_validator("host")
    @classmethod
    def _reject_ip_literal_host(cls, host: str) -> str:
        """Bare IP literals (RFC1918, loopback, the 169.254.169.254 cloud
        metadata address, ...) must never pass as a declared host — enforced
        here so it holds regardless of construction path, not only through
        parse_https_url()."""
        try:
            ipaddress.ip_address(host)
        except ValueError:
            return host
        raise ValueError(f"bare IP literals are not allowed as hosts: {host!r}")


class Adapter(BaseModel):
    name: str = Field(pattern=_NAME_PATTERN)
    endpoints: list[Endpoint]
    secrets: list[str] = Field(default_factory=list)
    description: str


def parse_https_url(url: str) -> tuple[str, int, str]:
    """host, port, path for a worry-supplied URL.

    HTTPS only; rejects bare IP literals (a cheap SSRF guard against
    metadata/RFC1918-style endpoints — forces a real DNS name). Query string and
    fragment are dropped: the policy never inspects them, so dynamic parameters
    belong there, not in the path.
    """
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise ValueError(f"only https URLs are allowed, got scheme {parsed.scheme!r}")
    host = parsed.hostname
    if not host:
        raise ValueError(f"URL has no hostname: {url!r}")
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError(f"bare IP literals are not allowed as hosts: {host!r}")
    port = parsed.port or 443
    path = parsed.path or "/"
    return host, port, path
