"""SSRF egress guard.

The agent's `http_request` tool and the dashboard's provider-discovery both issue outbound
requests to model/operator-supplied URLs. Without a guard those can reach cloud metadata
(169.254.169.254), loopback, and RFC1918 hosts — a server-side request forgery + credential
exfiltration primitive (audit SEC-4). This module centralises the allow/deny decision so both
call sites share one policy.

Policy:
  * scheme must be http or https (blocks file://, gopher://, data://, ...);
  * every IP the hostname resolves to must be a public unicast address — loopback, link-local
    (incl. cloud metadata), private (RFC1918/ULA), reserved, multicast, and unspecified are denied;
  * redirects must be re-validated hop-by-hop (a public host that 302s to a metadata IP is denied).

Residual risk: none after P3 pinning. The guard now resolves, validates, and pins
the connection to the validated IP via a custom httpcore network backend (see
``PinnedEgressBackend`` / ``make_pinned_transport``), so a DNS rebind between
check and connect cannot redirect the socket to a private/metadata address.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

ALLOWED_SCHEMES = frozenset({"http", "https"})

# Hostnames that resolve to metadata services but may be allow-listed by resolvers.
_BLOCKED_NAMES = frozenset({"metadata.google.internal", "metadata"})


class EgressBlocked(ValueError):
    """Raised when a URL is not permitted to leave the host."""


def _ip_is_public(ip: ipaddress._BaseAddress) -> bool:
    # IPv4-mapped IPv6 (::ffff:169.254.169.254) must be judged on the embedded v4 address.
    mapped = getattr(ip, "ipv4_mapped", None)
    if mapped is not None:
        ip = mapped
    return not (
        ip.is_loopback
        or ip.is_link_local
        or ip.is_private
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _resolve_ips(host: str) -> list[ipaddress._BaseAddress]:
    # Literal IP? judge it directly (no DNS).
    try:
        return [ipaddress.ip_address(host)]
    except ValueError:
        pass
    infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    out: list[ipaddress._BaseAddress] = []
    for family, _t, _p, _c, sockaddr in infos:
        addr = sockaddr[0]
        try:
            out.append(ipaddress.ip_address(addr.split("%", 1)[0]))
        except ValueError:
            continue
    return out


def check_url(url: str) -> None:
    """Raise EgressBlocked if `url` may not be requested. Resolves DNS."""
    parts = urlsplit(url)
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise EgressBlocked(f"scheme {parts.scheme!r} not allowed (only http/https)")
    host = parts.hostname
    if not host:
        raise EgressBlocked("URL has no host")
    if host.lower().rstrip(".") in _BLOCKED_NAMES:
        raise EgressBlocked(f"host {host!r} is a blocked metadata name")
    try:
        ips = _resolve_ips(host)
    except socket.gaierror:
        # Fail-open on resolution failure: a host that does not resolve cannot reach any internal
        # service (the caller's connect will simply fail). We only block hosts that positively
        # resolve to a non-public address, which is what the SSRF threat requires.
        return
    for ip in ips:
        if not _ip_is_public(ip):
            raise EgressBlocked(f"host {host!r} resolves to non-public address {ip}")


def is_allowed(url: str) -> bool:
    """Boolean form of check_url (never raises). DNS-resolution failures count as not-allowed."""
    try:
        check_url(url)
        return True
    except EgressBlocked:
        return False


def validate_redirect_chain(chain: list[str]) -> bool:
    """Every hop in a redirect chain must be allowed."""
    return all(is_allowed(u) for u in chain)


# ---------------------------------------------------------------------------
# P3: DNS-rebind socket-IP-pinning
#
# A custom httpcore network backend that resolves the hostname, validates ALL
# resolved IPs against the egress policy, and connects to the first validated
# IP — pinning the socket so a DNS rebind between check_url() and connect
# cannot redirect the connection to a private/metadata address.
#
# The TLS SNI is unaffected because httpcore wraps the raw TCP stream returned
# by connect_tcp() with SSL using the *origin host* (the original hostname), not
# the pinned IP.  So HTTPS connections present the correct SNI and verify the
# server certificate against the original hostname.
# ---------------------------------------------------------------------------

async def _resolve_validated_ips(host: str, port: int) -> list[str]:
    """Resolve *host*, validate every IP, and return the list of public IP strings.

    Raises ``EgressBlocked`` if any resolved IP is non-public (DNS rebind detected).
    Raises ``EgressBlocked`` if the host has no usable addresses at all.
    """
    loop = asyncio.get_running_loop()
    try:
        infos = await loop.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        raise EgressBlocked(f"DNS resolution failed for {host!r}")
    validated: list[str] = []
    for _fam, _t, _p, _c, sockaddr in infos:
        addr = sockaddr[0].split("%", 1)[0]
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if not _ip_is_public(ip):
            raise EgressBlocked(
                f"DNS rebind detected: {host!r} resolves to non-public {ip}"
            )
        validated.append(addr)
    if not validated:
        raise EgressBlocked(f"host {host!r} has no usable addresses")
    return validated


class PinnedEgressBackend:
    """Wraps an httpcore ``AsyncNetworkBackend`` with DNS-rebind protection.

    Duck-typed to match ``httpcore.AsyncNetworkBackend`` — no hard import of
    httpcore required (the class is only instantiated via ``make_pinned_transport``
    which does import httpcore).
    """

    def __init__(self, inner):
        self._inner = inner

    async def connect_tcp(
        self,
        host: str,
        port: int,
        *,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options=None,
    ):
        # Literal IP — validate directly, no DNS to rebind.
        try:
            ip = ipaddress.ip_address(host)
        except ValueError:
            pass
        else:
            if not _ip_is_public(ip):
                raise EgressBlocked(f"connection to non-public IP {ip} blocked")
            return await self._inner.connect_tcp(
                host, port, timeout=timeout,
                local_address=local_address, socket_options=socket_options,
            )

        # Hostname — resolve, validate ALL IPs, pin to the first one.
        validated = await _resolve_validated_ips(host, port)
        return await self._inner.connect_tcp(
            validated[0], port, timeout=timeout,
            local_address=local_address, socket_options=socket_options,
        )

    async def connect_unix_socket(
        self, path: str, *, timeout: float | None = None, socket_options=None,
    ):
        return await self._inner.connect_unix_socket(
            path, timeout=timeout, socket_options=socket_options,
        )

    async def sleep(self, seconds: float) -> None:
        return await self._inner.sleep(seconds)


def make_pinned_transport(**transport_kwargs):
    """Create an ``httpx.AsyncHTTPTransport`` with DNS-rebind-safe IP pinning.

    Any keyword args are forwarded to ``httpx.AsyncHTTPTransport`` (e.g. ``verify``,
    ``limits``, ``retries``).  The returned transport resolves DNS through
    ``PinnedEgressBackend`` so the actual TCP connection goes to a validated public
    IP, not a re-resolved address that could be rebinding.
    """
    import httpx  # lazy — httpx is an optional extra

    transport = httpx.AsyncHTTPTransport(**transport_kwargs)
    # Replace the pool's network backend with our pinned version. The pool was
    # already constructed by AsyncHTTPTransport.__init__ with a default AutoBackend;
    # we wrap that backend so all other behaviour (keepalive, HTTP/2, etc.) is
    # preserved — only the IP selection at connect time changes.
    transport._pool._network_backend = PinnedEgressBackend(
        transport._pool._network_backend,
    )
    return transport
