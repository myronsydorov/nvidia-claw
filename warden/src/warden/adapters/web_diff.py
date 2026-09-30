"""Watch one worry-supplied web page for meaningful changes.

Generic adapter: the host isn't known until a worry names a specific URL, so
`declare` builds the Adapter at compile time instead of exposing a static
constant. Uses warden.adapters.base.parse_https_url for the SSRF guard
(https-only, no bare IP literals) and to derive the one exact declared path.
"""

from warden.adapters.base import Adapter, Endpoint, parse_https_url


def declare(*, url: str, why: str) -> Adapter:
    host, port, path = parse_https_url(url)
    return Adapter(
        name="web_diff",
        endpoints=[Endpoint(host=host, port=port, path=path, why=why)],
        description="Fetch a specific web page and detect meaningful changes since the last check",
    )
