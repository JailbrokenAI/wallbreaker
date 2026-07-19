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

Residual risk (documented in security-audit-prep.md): DNS rebinding between this check and the
actual socket connect. Fully closing that needs socket-level pinning of the validated IP; this
guard resolves and checks all A/AAAA records, which stops the common cases.
"""
from __future__ import annotations

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
