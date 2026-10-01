"""Every host a watcher may reach must resolve to public addresses only (THREAT_MODEL A2).

Measured on OpenShell 0.0.116 (ADR-0001): its SSRF engine always blocks names that resolve
to loopback or link-local (169.254.169.254 included), but a name resolving to an RFC 1918
or Docker-bridge address was not refused. A worry can name any host (`127.0.0.1.nip.io`,
a static private A record), so the compiler checks before the dry run and approve checks
again before the sandbox gets its policy. A name that changes its answer later (DNS
rebinding) is still out of scope (THREAT_MODEL).
"""

import asyncio
import ipaddress
import socket
from collections.abc import Awaitable, Callable, Iterable

Resolver = Callable[[str, int], Awaitable[list[str]]]


async def system_resolve(host: str, port: int) -> list[str]:
    infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
    return sorted({str(info[4][0]) for info in infos})


# Swapped for a stub in unit tests (no live DNS there).
resolve: Resolver = system_resolve


async def non_public_host(endpoints: Iterable[tuple[str, int]]) -> str | None:
    """None if every (host, port) resolves only to global addresses, else our own message."""
    for host, port in sorted(set(endpoints)):
        try:
            addresses = await resolve(host, port)
        except OSError:
            return f"{host} could not be found"
        if not addresses:
            return f"{host} could not be found"
        for address in addresses:
            ip = ipaddress.ip_address(address.split("%", 1)[0])
            if not ip.is_global:
                return f"{host} points at a private or local address"
    return None
