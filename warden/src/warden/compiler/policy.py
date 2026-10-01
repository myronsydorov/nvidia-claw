"""Adapter declarations -> OpenShell sandbox policy YAML + policy_summary.

The schema is OpenShell 0.0.116's sandbox policy, pinned by the T-04 spike (ADR-0001):
a fixed filesystem/process baseline plus one `network_policies` entry per (host, port),
whose `rules` allow exactly the declared GET paths for the watcher's Python interpreter.
Everything else is denied by OpenShell's default-deny proxy and logged.

- `protocol: rest` + `enforcement: enforce` makes the proxy check method and path (L7), not
  only the host. Paths are already in OpenShell's canonical form (`adapters.base`).
- `allow_encoded_slash` is never set (OpenShell's default refuses `%2F`).
- `binaries` names the interpreter's real path: OpenShell identifies the caller by it, so
  nothing else in the sandbox (a shell, pip) gets the watcher's egress.
- The filesystem baseline can't be narrowed on a live sandbox, so `/w` (where run.py is
  uploaded after create) stays writable; the compiler's gate limits generated `open()` to
  /tmp/, so approved code can't rewrite itself.
"""

from typing import Any

import yaml

from warden.adapters.base import Adapter, Endpoint
from warden.models import PermissionLine

WATCHER_BINARY = "/usr/local/bin/python3.12"  # the real path in custody-watcher images

_BASELINE: dict[str, Any] = {
    "version": 1,
    "filesystem_policy": {
        "include_workdir": False,
        "read_only": ["/usr", "/lib", "/proc", "/dev/urandom", "/etc"],
        "read_write": ["/tmp", "/dev/null", "/sandbox", "/w"],
    },
    "landlock": {"compatibility": "strict"},
    "process": {"run_as_user": "sandbox", "run_as_group": "sandbox"},
}


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


def _policy_key(host: str, port: int) -> str:
    return "custody_" + host.replace(".", "_").replace("-", "_") + f"_{port}"


def baseline_policy_yaml() -> str:
    """The policy a watcher sandbox is created with: the baseline and no network at all."""
    return yaml.safe_dump({**_BASELINE, "network_policies": {}}, sort_keys=False)


def generate_policy(adapters: list[Adapter], sandbox_name: str) -> tuple[str, list[PermissionLine]]:
    """Return (policy_yaml, policy_summary) for a watcher using exactly `adapters`.

    Deduplicates identical (host, port, method, path) endpoints declared by more
    than one adapter; raises ValueError if two such endpoints disagree on `why`.
    """
    endpoints = _dedupe(adapters)
    groups: dict[tuple[str, int], list[Endpoint]] = {}
    for e in endpoints:
        groups.setdefault((e.host, e.port), []).append(e)
    network_policies = {
        _policy_key(host, port): {
            "name": _policy_key(host, port),
            "endpoints": [
                {
                    "host": host,
                    "port": port,
                    "protocol": "rest",
                    "enforcement": "enforce",
                    "rules": [{"allow": {"method": e.method, "path": e.path}} for e in group],
                }
            ],
            "binaries": [{"path": WATCHER_BINARY}],
        }
        for (host, port), group in groups.items()
    }
    header = f"# Custody watcher policy for {sandbox_name}: generated from adapter declarations\n"
    document = {**_BASELINE, "network_policies": network_policies}
    policy_yaml = header + yaml.safe_dump(document, sort_keys=False, default_flow_style=False)
    policy_summary = [
        PermissionLine(method=e.method, host=e.host, path=e.path, why=e.why) for e in endpoints
    ]
    return policy_yaml, policy_summary


def egress_rules(policy_yaml: str) -> set[tuple[str, int, str, str]]:
    """Every (host, port, method, path) a policy allows: what tests and the driver check."""
    doc = yaml.safe_load(policy_yaml)
    rules: set[tuple[str, int, str, str]] = set()
    for entry in (doc.get("network_policies") or {}).values():
        for endpoint in entry["endpoints"]:
            for rule in endpoint["rules"]:
                allow = rule["allow"]
                rules.add((endpoint["host"], endpoint["port"], allow["method"], allow["path"]))
    return rules
