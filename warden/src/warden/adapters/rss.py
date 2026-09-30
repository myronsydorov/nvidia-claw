"""Watch a worry-supplied RSS/Atom feed for new items.

Generic adapter, same shape as web_diff/http_json: the host isn't known until a
worry names a specific feed URL.
"""

from warden.adapters.base import Adapter, Endpoint, parse_https_url


def declare(*, url: str, why: str) -> Adapter:
    host, port, path = parse_https_url(url)
    return Adapter(
        name="rss",
        endpoints=[Endpoint(host=host, port=port, path=path, why=why)],
        description="Check an RSS/Atom feed for new items",
    )
