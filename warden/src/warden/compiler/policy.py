"""Adapter declarations -> OpenShell network-policy YAML + policy_summary.

The real OpenShell policy CLI syntax isn't pinned yet (ADR-0001's spike, T-04, is
still open), so the emitted YAML is deliberately minimal: a sandbox name and an
ordered egress list, nothing more. Do not add structure (version markers, a
default-deny key, ...) that implies a schema this repo hasn't verified against a
real `openshell` host.
"""

import yaml

from warden.adapters.base import Adapter, Endpoint
from warden.models import PermissionLine

_HEADER = "# provisional policy schema — real OpenShell CLI syntax pinned by T-04 (ADR-0001)\n"


def _dedupe(adapters: list[Adapter]) -> list[Endpoint]:
    seen: dict[tuple[str, int, str, str], Endpoint] = {}
    for adapter in adapters:
        for endpoint in adapter.endpoints:
            key = (endpoint.host, endpoint.port, endpoint.method, endpoint.path)
            existing = seen.get(key)
            if existing is None:
                seen[key] = endpoint
            elif existing.why != endpoint.why:
                raise ValueError(
                    f"conflicting 'why' for {key}: {existing.why!r} vs {endpoint.why!r}"
                )
    return list(seen.values())


def generate_policy(adapters: list[Adapter], sandbox_name: str) -> tuple[str, list[PermissionLine]]:
    """Return (policy_yaml, policy_summary) for a watcher using exactly `adapters`.

    Deduplicates identical (host, port, method, path) endpoints declared by more
    than one adapter; raises ValueError if two such endpoints disagree on `why`.
    """
    endpoints = _dedupe(adapters)
    document = {
        "sandbox": sandbox_name,
        "egress": [
            {
                "host": e.host,
                "port": e.port,
                "method": e.method,
                "path": e.path,
                "why": e.why,
            }
            for e in endpoints
        ],
    }
    policy_yaml = _HEADER + yaml.safe_dump(document, sort_keys=False, default_flow_style=False)
    policy_summary = [
        PermissionLine(method=e.method, host=e.host, path=e.path, why=e.why) for e in endpoints
    ]
    return policy_yaml, policy_summary
