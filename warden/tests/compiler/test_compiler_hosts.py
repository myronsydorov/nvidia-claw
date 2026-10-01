"""Worry-supplied hosts must resolve to public addresses only (T-04 security review)."""

import asyncio
from collections.abc import Callable

import pytest
from warden.compiler import hosts


@pytest.fixture
def check(monkeypatch: pytest.MonkeyPatch) -> Callable[[list[str] | OSError], str | None]:
    def run(answer: list[str] | OSError) -> str | None:
        async def fake(host: str, port: int) -> list[str]:
            if isinstance(answer, OSError):
                raise answer
            return answer

        monkeypatch.setattr(hosts, "resolve", fake)
        return asyncio.run(hosts.non_public_host([("cal.example.com", 443)]))

    return run


Check = Callable[[list[str] | OSError], str | None]


@pytest.mark.parametrize(
    "addresses",
    [["127.0.0.1"], ["10.19.0.5"], ["172.17.0.1"], ["169.254.169.254"], ["100.81.50.38"],
     ["::1"], ["fd7a:115c:a1e0::1"], ["fe80::1%eth0"], ["93.184.215.14", "192.168.1.1"]],
)
def test_private_or_local_addresses_are_refused(check: Check, addresses: list[str]) -> None:
    assert check(addresses) == "cal.example.com points at a private or local address"


def test_public_addresses_pass(check: Check) -> None:
    assert check(["93.184.215.14", "2606:2800:21f:cb07:6820:80da:af6b:8b2c"]) is None


def test_unresolvable_or_empty_is_refused(check: Check) -> None:
    assert check(OSError("nxdomain")) == "cal.example.com could not be found"
    assert check([]) == "cal.example.com could not be found"
