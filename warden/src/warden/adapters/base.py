"""AdapterDeclaration shapes (docs/CONTRACTS.md §1) and a shared URL-parsing guard.

`Endpoint`/`Adapter` are compiler-internal: they describe what a watcher may call
over the network and feed the policy generator (warden.compiler.policy). They are
never serialized to /api, so they do not belong in warden.models (which mirrors the
public contract + app/src/api/schemas.ts).

Every declared path is an exact literal path, never a prefix or wildcard — dynamic
identifiers belong in the query string, or get baked into one exact path string at
declare-time (see warden.adapters.transit_bvg). AGENTS.md invariant #2: no wildcard
hosts, no hand-widening, GET-only unless an ADR says otherwise.

Paths are declared in OpenShell's *canonical* form (T-04 spike, ADR-0001). OpenShell's L7
proxy canonicalizes the request path before matching it, literally, against the rule's
glob: an escape of a character that is legal in a path (`%40`, `%2B`, `%3A`, `%2A`, ...) is
decoded, every other escape stays encoded (`%23`, `%20`, `%25`, any hex case), dot segments
are resolved and `//` merged; `%2F`, `%00` and malformed escapes are refused outright. A rule
written as `/a%40b` therefore never matches anything, and one written with a `*` would be a
glob. `canonical_path` produces exactly that form and refuses anything that would be a glob
character, a path parameter (`;`, which OpenShell strips before matching), an encoded slash, a
control byte, or a dot or empty segment.
"""

import ipaddress
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, field_validator

_HOST_PATTERN = r"^[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+$"
# The characters a canonical path may hold: unreserved, a few harmless sub-delims, ':' and '@'
# (never '*', a glob, nor ';', a path parameter), plus %XX for the bytes OpenShell keeps encoded.
_PATH_PATTERN = r"^/([A-Za-z0-9._~+=,:@/-]|%[0-9A-F]{2})*$"
_LITERAL = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-._~+=,:@")
# RFC 3986 pchar minus '/': OpenShell decodes an escape of any of these before matching.
_DECODED_BY_OPENSHELL = _LITERAL | frozenset("!$&'()*;")
_HEX = frozenset("0123456789abcdefABCDEF")
_NAME_PATTERN = r"^[a-z][a-z0-9_]*$"


class Endpoint(BaseModel):
    host: str = Field(pattern=_HOST_PATTERN)
    port: int = Field(default=443, ge=1, le=65535)
    method: Literal["GET"] = "GET"
    path: str = Field(pattern=_PATH_PATTERN)
    why: str = Field(min_length=1)

    @field_validator("path")
    @classmethod
    def _require_canonical_path(cls, path: str) -> str:
        if canonical_path(path) != path:
            raise ValueError(f"path is not in OpenShell's canonical form: {path!r}")
        return path

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


def canonical_path(raw: str) -> str:
    """The path OpenShell will compare against the policy rule, or ValueError if it can't be
    declared safely (see the module docstring). Non-ASCII characters become UTF-8 escapes."""
    if not raw.startswith("/"):
        raise ValueError(f"path must start with '/': {raw!r}")
    out: list[str] = []
    i = 0
    while i < len(raw):
        char = raw[i]
        if char == "%":
            hex_digits = raw[i + 1 : i + 3]
            if len(hex_digits) != 2 or not set(hex_digits) <= _HEX:
                raise ValueError(f"malformed percent-escape in path: {raw!r}")
            byte = int(hex_digits, 16)
            if byte == 0x2F or byte < 0x20 or byte == 0x7F:
                raise ValueError(f"encoded slash or control byte in path: {raw!r}")
            decoded = chr(byte)
            if byte < 0x80 and decoded in _DECODED_BY_OPENSHELL:
                if decoded not in _LITERAL:
                    raise ValueError(f"path contains a glob or path-parameter character: {raw!r}")
                out.append(decoded)
            else:
                out.append(f"%{byte:02X}")
            i += 3
            continue
        if char == "/" or char in _LITERAL:
            out.append(char)
        elif ord(char) > 0x7F:
            out.extend(f"%{b:02X}" for b in char.encode("utf-8"))
        else:
            raise ValueError(f"character {char!r} is not allowed in a declared path: {raw!r}")
        i += 1
    path = "".join(out)
    segments = path.split("/")[1:]
    for index, segment in enumerate(segments):
        if segment in (".", ".."):
            raise ValueError(f"dot segment in path: {raw!r}")
        if segment == "" and index != len(segments) - 1:
            raise ValueError(f"empty segment ('//') in path: {raw!r}")
    return path


def parse_https_url(url: str) -> tuple[str, int, str]:
    """host, port, path for a worry-supplied URL.

    HTTPS only; rejects bare IP literals (a cheap SSRF guard against
    metadata/RFC1918-style endpoints — forces a real DNS name). Query string and
    fragment are dropped: the policy never inspects them, so dynamic parameters
    belong there, not in the path. The path comes back canonical (`canonical_path`).
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
    path = canonical_path(parsed.path or "/")
    return host, port, path
