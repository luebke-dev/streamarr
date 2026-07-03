"""SSRF-hardened outbound fetch helpers.

Any HTTP fetch whose target URL is (even indirectly) influenced by user input
must go through :func:`assert_safe_url` / :func:`safe_get` so it cannot be
pointed at loopback, link-local, or private-network addresses (cloud metadata
services, internal admin panels, other containers).

The guard resolves every candidate host to its IP addresses and rejects the
request if any of them is private/loopback/link-local/reserved. Redirects are
validated per hop, which closes the "allowlisted host 302s to 169.254.169.254"
and DNS-rebinding-on-redirect bypasses.
"""

import ipaddress
import socket

import httpx

from pyrate.utils.http import make_async_client

__all__ = ["UnsafeUrlError", "assert_safe_url", "safe_get"]


class UnsafeUrlError(ValueError):
    """Raised when a URL targets a disallowed (internal) address or scheme."""


def _ip_is_disallowed(
    ip: ipaddress.IPv4Address | ipaddress.IPv6Address, *, block_private: bool
) -> bool:
    # Loopback, link-local (cloud metadata at 169.254.169.254), reserved,
    # multicast and unspecified are never legitimate fetch targets. Private
    # RFC1918 ranges are only blocked in strict mode: a self-hosted server
    # legitimately talks to LAN/Docker-network services (indexers, OIDC,
    # subtitle providers), so admin-configured fetches allow them while
    # user-supplied URLs (block_private=True) do not.
    if (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    ):
        return True
    return block_private and ip.is_private


def _resolve_host(host: str) -> list[ipaddress._BaseAddress]:
    # A bare IP literal resolves to itself; getaddrinfo covers hostnames.
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UnsafeUrlError(f"Cannot resolve host: {host}") from exc
    addrs: list[ipaddress._BaseAddress] = []
    for info in infos:
        sockaddr = info[4]
        try:
            addrs.append(ipaddress.ip_address(sockaddr[0]))
        except ValueError:
            continue
    if not addrs:
        raise UnsafeUrlError(f"Cannot resolve host: {host}")
    return addrs


def assert_safe_url(
    url: str,
    *,
    allowed_schemes: tuple[str, ...] = ("https", "http"),
    block_private: bool = False,
) -> None:
    """Raise :class:`UnsafeUrlError` if ``url`` is not safe to fetch.

    Validates the scheme and that no resolved IP of the host is loopback,
    link-local (cloud metadata), reserved, multicast or unspecified. Set
    ``block_private=True`` for user-supplied URLs to additionally reject
    private RFC1918 ranges. Callers that follow redirects must re-validate
    each hop (see :func:`safe_get`).
    """
    parts = httpx.URL(url)
    if parts.scheme not in allowed_schemes:
        raise UnsafeUrlError(f"Disallowed scheme: {parts.scheme!r}")
    host = parts.host
    if not host:
        raise UnsafeUrlError("URL has no host")
    for ip in _resolve_host(host):
        if _ip_is_disallowed(ip, block_private=block_private):
            raise UnsafeUrlError(f"URL resolves to a disallowed address: {ip}")


async def safe_get(
    url: str,
    *,
    client: httpx.AsyncClient | None = None,
    max_redirects: int = 5,
    allowed_schemes: tuple[str, ...] = ("https", "http"),
    block_private: bool = False,
    **kwargs,
) -> httpx.Response:
    """GET ``url`` with SSRF validation on the initial URL and every redirect.

    Redirects are followed manually so each hop is re-validated (``httpx``'s
    ``follow_redirects`` would skip the per-hop check). Pass an existing
    ``client`` to reuse connection pools; otherwise a short-lived one is used.
    Set ``block_private=True`` for user-supplied URLs to also reject RFC1918.
    """
    own_client = client is None
    http = client or make_async_client()
    try:
        current = url
        for _ in range(max_redirects + 1):
            assert_safe_url(
                current, allowed_schemes=allowed_schemes, block_private=block_private
            )
            response = await http.get(current, follow_redirects=False, **kwargs)
            if response.is_redirect and response.has_redirect_location:
                current = str(response.headers["location"])
                if not httpx.URL(current).is_absolute_url:
                    current = str(response.url.join(current))
                continue
            return response
        raise UnsafeUrlError("Too many redirects")
    finally:
        if own_client:
            await http.aclose()
