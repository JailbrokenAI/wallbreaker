"""Dashboard authentication + CSRF/Origin enforcement.

The dashboard used to be a fully unauthenticated local API whose routes could spawn shell
commands, write API keys to .env, and fire attacks — reachable via browser CSRF from any page
the operator visited, and via the LAN if bound to 0.0.0.0 (audit SEC-1/2/3/6). This module adds:

  * a per-launch bearer token (generated on `serve()`, printed to the console, written 0600);
  * a pure-ASGI SecurityMiddleware that requires the token AND a same-origin request on every
    /api/* route (except a small exempt set), rejecting cross-site requests before any handler
    side effect. Pure-ASGI (not BaseHTTPMiddleware) so it never buffers the SSE streams.

CORS is NOT an access control — Starlette's CORSMiddleware only decides response headers and lets
the handler run regardless. This middleware actually rejects the request.
"""
from __future__ import annotations

import hmac
import json
import os
import secrets
from pathlib import Path
from urllib.parse import urlsplit

TOKEN_HEADER = "x-wb-token"
CSRF_HEADER = "x-wb-csrf"
TOKEN_FILENAME = ".wallbreaker_dashboard_token"

# Paths reachable without a token (health probe + the same-origin bootstrap the SPA uses to
# learn the token). Everything else under /api/ requires auth when require_auth is True.
EXEMPT_PATHS = frozenset({"/api/health", "/api/session"})

_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", ""})


def token_file_path(base: str | Path | None = None) -> Path:
    return Path(base or ".") / TOKEN_FILENAME


def ensure_launch_token(base: str | Path | None = None) -> str:
    """Generate (or reuse) the launch token and persist it 0600 so the SPA can read it."""
    token = secrets.token_urlsafe(32)
    path = token_file_path(base)
    # Write with 0600 from creation (don't chmod-after, which briefly exposes it).
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(token)
    try:
        os.chmod(path, 0o600)
    except OSError:
        pass
    return token


def _bearer(auth_header: str | None) -> str | None:
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header[7:].strip()
    return None


def origin_is_same_site(origin: str | None) -> bool:
    """A localhost dashboard's only legitimate Origin is a loopback host. Absent Origin means a
    non-browser client (curl / the CLI / a test) which cannot be a CSRF victim → allowed."""
    if origin is None:
        return True
    host = urlsplit(origin).hostname or ""
    return host.lower() in _LOOPBACK_HOSTS


class SecurityMiddleware:
    """Pure-ASGI token + Origin gate. Streaming responses pass through untouched."""

    def __init__(self, app, token: str, require_auth: bool = True,
                 exempt_paths: frozenset[str] = EXEMPT_PATHS):
        self.app = app
        self.token = token
        self.require_auth = require_auth
        self.exempt_paths = exempt_paths

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or not self.require_auth:
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        if not path.startswith("/api/") or path in self.exempt_paths:
            await self.app(scope, receive, send)
            return

        headers = {k.decode("latin-1").lower(): v.decode("latin-1")
                   for k, v in scope.get("headers", [])}

        # CSRF: reject any cross-site Origin (and Sec-Fetch-Site: cross-site) before the handler.
        if not origin_is_same_site(headers.get("origin")):
            await self._reject(send, 403, "cross-site request blocked")
            return
        if headers.get("sec-fetch-site") in {"cross-site", "same-site"}:
            await self._reject(send, 403, "cross-site request blocked")
            return

        supplied = headers.get(TOKEN_HEADER) or _bearer(headers.get("authorization"))
        if not supplied or not hmac.compare_digest(supplied, self.token):
            await self._reject(send, 401, "missing or invalid dashboard token")
            return

        await self.app(scope, receive, send)

    async def _reject(self, send, status: int, detail: str) -> None:
        body = json.dumps({"detail": detail}).encode("utf-8")
        await send({
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode())],
        })
        await send({"type": "http.response.body", "body": body})
