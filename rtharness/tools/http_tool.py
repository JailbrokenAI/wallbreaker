from __future__ import annotations

import json

import httpx

from .registry import ToolContext, ToolRegistry

MAX_BODY = 30000


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

    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            resp = await client.request(method, url, **kwargs)
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
