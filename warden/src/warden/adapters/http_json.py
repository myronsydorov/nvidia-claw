"""Poll a worry-supplied JSON endpoint.

Generic adapter, same shape as web_diff: the host isn't known until a worry
names a specific URL. `secrets` lets the compiler name a bearer-token env var
(or similar) the watcher needs for that specific integration, injected by the
OpenShell provider at the network boundary — never written into code.
"""

from warden.adapters.base import Adapter, Endpoint, parse_https_url


def declare(*, url: str, why: str, secrets: list[str] | None = None) -> Adapter:
    host, port, path = parse_https_url(url)
    return Adapter(
        name="http_json",
        endpoints=[Endpoint(host=host, port=port, path=path, why=why)],
        secrets=secrets or [],
        description="Fetch a JSON endpoint and evaluate a condition against the response",
    )
