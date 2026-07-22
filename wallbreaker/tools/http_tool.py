from __future__ import annotations

import json

import httpx

from .egress_guard import EgressBlocked, check_url, make_pinned_transport
from .registry import ToolContext, ToolRegistry

MAX_BODY = 30000
MAX_REDIRECTS = 5


async def _http_request(args: dict, ctx: ToolContext) -> str:
    url = args.get("url", "")
    if not url:
        return "Error: 'url' is required"
    method = str(args.get("method", "GET")).upper()
    headers = args.get("headers") or {}
    body = args.get("body")
    json_body = args.get("json")
    timeout = float(args.get("timeout", 60))

    kwargs: dict = {"headers": headers}
    if json_body is not None:
        kwargs["json"] = json_body
    elif body is not None:
        kwargs["content"] = body if isinstance(body, str) else json.dumps(body)

    # SSRF guard: validate the initial URL and every redirect hop against the egress policy
    # (blocks metadata/loopback/private targets). We follow redirects manually so each Location
    # is re-checked before we connect to it — httpx's follow_redirects=True would chase a
    # public-host -> 169.254.169.254 redirect without a second look.
    try:
        check_url(url)
    except EgressBlocked as exc:
        return f"Request blocked: {exc}"

    try:
        async with httpx.AsyncClient(
            timeout=timeout, follow_redirects=False,
            transport=make_pinned_transport(),
        ) as client:
            resp = await client.request(method, url, **kwargs)
            hops = 0
            while resp.is_redirect and hops < MAX_REDIRECTS:
                location = resp.headers.get("location")
                if not location:
                    break
                next_url = str(resp.next_request.url) if resp.next_request else location
                try:
                    check_url(next_url)
                except EgressBlocked as exc:
                    return f"Request blocked (redirect): {exc}"
                hops += 1
                resp = await client.request(method, next_url, **kwargs)
    except httpx.HTTPError as exc:
        return f"Request failed: {exc}"

    text = resp.text
    if len(text) > MAX_BODY:
        text = text[:MAX_BODY] + f"\n... (truncated, {len(text)} bytes)"
    head_lines = "\n".join(f"{k}: {v}" for k, v in resp.headers.items())
    return f"HTTP {resp.status_code}\n{head_lines}\n\n{text}"


def register(registry: ToolRegistry) -> None:
    registry.add(
        name="http_request",
        description=(
            "Make an arbitrary HTTP request and return the status, headers, and body. "
            "Use to deliver raw payloads to a custom target endpoint or webhook."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "method": {"type": "string", "description": "GET/POST/PUT/etc"},
                "headers": {"type": "object"},
                "body": {"type": "string", "description": "Raw request body"},
                "json": {"type": "object", "description": "JSON request body"},
                "timeout": {"type": "number"},
            },
            "required": ["url"],
        },
        handler=_http_request,
    )
