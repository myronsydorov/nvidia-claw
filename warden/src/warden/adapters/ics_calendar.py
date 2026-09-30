"""Watch a worry-supplied ICS calendar feed for new or changed events.

Generic adapter, same shape as web_diff/http_json/rss: the host isn't known
until a worry names a specific calendar URL.
"""

from warden.adapters.base import Adapter, Endpoint, parse_https_url


def declare(*, url: str, why: str) -> Adapter:
    host, port, path = parse_https_url(url)
    return Adapter(
        name="ics_calendar",
        endpoints=[Endpoint(host=host, port=port, path=path, why=why)],
        description="Check an ICS calendar feed for new or changed events",
    )
