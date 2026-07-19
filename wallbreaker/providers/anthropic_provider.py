from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from ..agent.messages import (
    Message,
    ReasoningDelta,
    StreamEvent,
    StopEvent,
    TextBlock,
    TextDelta,
    ToolResultBlock,
    ToolUseBlock,
    ToolUseEvent,
    UsageEvent,
)
from .base import _POOL_LIMITS, Provider, ProviderError, _http2_ok, parse_tool_args
from .request_gate import gated_stream

ANTHROPIC_VERSION = "2023-06-01"

_CACHE_CONTROL = {"type": "ephemeral"}


def _cache_control(ttl: str = "5m") -> dict:
    """The cache_control marker. Bare ephemeral = Anthropic's 5m default; ttl='1h' requests
    the extended window (needs the extended-cache-ttl beta header, added in stream())."""
    return {"type": "ephemeral", "ttl": "1h"} if ttl == "1h" else {"type": "ephemeral"}


def _tools_to_wire(tools: list[dict], cache: bool = False, ttl: str = "5m") -> list[dict]:
    wire = [
        {
            "name": t["name"],
            "description": t.get("description", ""),
            "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
        }
        for t in tools
    ]
    # One cache_control on the LAST tool marks the whole tools array as a cacheable prefix
    # segment (Anthropic processes tools before system before messages). The 93-tool spec is
    # ~27K static tokens - caching it turns that into a ~0.1x re-read every subsequent round.
    if cache and wire:
        wire[-1] = {**wire[-1], "cache_control": _cache_control(ttl)}
    return wire


def _mark_history_cache(wire: list[dict], breakpoints: int = 2, ttl: str = "5m") -> None:
    """Add rolling cache_control breakpoints to the tail of the conversation in place.

    Marks the last content block of the last N messages. Each breakpoint makes everything
    BEFORE it a cacheable prefix, so the next round (same prefix + one more turn appended)
    re-reads the whole prior conversation from cache at ~0.1x instead of re-billing the full
    O(n) history. Two breakpoints give resilience: even if the very last one just missed the
    5-min TTL, the earlier one still covers most of the transcript.
    """
    cc = _cache_control(ttl)
    marked = 0
    for entry in reversed(wire):
        if marked >= breakpoints:
            break
        content = entry.get("content")
        if isinstance(content, list) and content:
            content[-1] = {**content[-1], "cache_control": cc}
            marked += 1


def _messages_to_wire(messages: list[Message], merge_system: str | None = None) -> list[dict]:
    wire: list[dict] = []
    injected = False
    for msg in messages:
        if msg.role == "system":
            continue
        blocks: list[dict] = []
        for b in msg.content:
            if isinstance(b, TextBlock):
                if b.text:
                    blocks.append({"type": "text", "text": b.text})
            elif isinstance(b, ToolUseBlock):
                blocks.append(
                    {"type": "tool_use", "id": b.id, "name": b.name, "input": b.input}
                )
            elif isinstance(b, ToolResultBlock):
                blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": b.tool_use_id,
                        "content": b.content,
                        "is_error": b.is_error,
                    }
                )
        if merge_system and not injected and msg.role == "user":
            blocks = [{"type": "text", "text": merge_system}] + blocks
            injected = True
        if blocks:
            wire.append({"role": msg.role, "content": blocks})
    if merge_system and not injected:  # no user turn to merge into - add one
        wire.append({"role": "user", "content": [{"type": "text", "text": merge_system}]})
    return wire


class AnthropicProvider(Provider):
    supports_native_prefill = True

    def _make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.timeout, limits=_POOL_LIMITS, http2=_http2_ok(),
            follow_redirects=True,
        )

    def _auth_headers(self) -> dict:
        """Request headers. Native Anthropic authenticates with x-api-key; third-party
        proxies (tokies.cc, etc.) use Authorization: Bearer (the ANTHROPIC_AUTH_TOKEN
        scheme). endpoint.auth_style='bearer' selects the latter."""
        headers = {
            "anthropic-version": ANTHROPIC_VERSION,
            "Content-Type": "application/json",
        }
        key = self.endpoint.require_key()
        if getattr(self.endpoint, "auth_style", "x-api-key") == "bearer":
            headers["Authorization"] = f"Bearer {key}"
        else:
            headers["x-api-key"] = key
        return headers

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float | None = None,
    ) -> AsyncIterator[StreamEvent]:
        async for event in gated_stream(
            self.endpoint,
            lambda: self._stream_ungated(
                messages,
                tools=tools,
                system=system,
                max_tokens=max_tokens,
                temperature=temperature,
            ),
        ):
            yield event

    async def _stream_ungated(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float | None = None,
    ) -> AsyncIterator[StreamEvent]:
        path = getattr(self.endpoint, "inference_path", "") or "/v1/messages"
        url = f"{self.endpoint.base_url}{path if path.startswith('/') else '/' + path}"
        headers = self._auth_headers()
        cache = bool(getattr(self.endpoint, "cache", True))
        ttl = getattr(self.endpoint, "cache_ttl", "5m")
        if cache:
            # Harmless on GA models (they cache without it); required by older snapshots.
            betas = ["prompt-caching-2024-07-31"]
            if ttl == "1h":
                betas.append("extended-cache-ttl-2025-04-11")
            headers["anthropic-beta"] = ",".join(betas)
        mode = getattr(self.endpoint, "system_mode", "default")
        merge_system = system if (mode == "merge" and system) else None
        wire_messages = _messages_to_wire(messages, merge_system=merge_system)
        if cache:
            _mark_history_cache(wire_messages, ttl=ttl)
        payload: dict = {
            "model": self.endpoint.model,
            "messages": wire_messages,
            "max_tokens": max_tokens,
            "stream": True,
        }
        if system and mode == "default":
            # As a single cacheable text block, the ~11K static system prompt is re-read at
            # ~0.1x on every round after the first instead of re-billed in full.
            payload["system"] = (
                [{"type": "text", "text": system, "cache_control": _cache_control(ttl)}]
                if cache
                else system
            )
        if temperature is not None:
            payload["temperature"] = temperature
        if tools:
            payload["tools"] = _tools_to_wire(tools, cache=cache, ttl=ttl)
            tc = getattr(self, "tool_choice", None) or getattr(
                self.endpoint, "tool_choice", None
            )
            if tc:
                # Anthropic: "any" forces a tool call; "auto" is default; "tool" pins one.
                if tc in ("required", "any"):
                    payload["tool_choice"] = {"type": "any"}
                elif tc == "auto":
                    payload["tool_choice"] = {"type": "auto"}
                elif isinstance(tc, dict):
                    payload["tool_choice"] = tc
                else:
                    payload["tool_choice"] = {"type": str(tc)}
        if getattr(self.endpoint, "reasoning", False):
            # Extended thinking: budget must be >=1024 and strictly < max_tokens, and
            # temperature must be unset while thinking is enabled.
            budget = max(1024, max_tokens // 2)
            if payload["max_tokens"] <= budget:
                payload["max_tokens"] = budget + 1024
            payload["thinking"] = {"type": "enabled", "budget_tokens": budget}
            payload.pop("temperature", None)

        blocks: dict[int, dict] = {}
        content_chars = 0
        thinking_parts: list[str] = []
        stop_reason: str | None = None
        self.last_stop_reason = None
        self.last_completion_empty = False
        client = self._http_client()
        try:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                    if resp.status_code >= 400:
                        body = (await resp.aread()).decode("utf-8", "replace")
                        raise ProviderError(f"HTTP {resp.status_code} from {url}: {body}")
                    async for line in resp.aiter_lines():
                        if not line.startswith("data:"):
                            continue
                        data = line[5:].strip()
                        if not data:
                            continue
                        try:
                            event = json.loads(data)
                        except json.JSONDecodeError:
                            continue
                        etype = event.get("type")
                        if etype == "message_start":
                            usage = (event.get("message") or {}).get("usage") or {}
                            if usage:
                                yield UsageEvent(
                                    input_tokens=usage.get("input_tokens", 0),
                                    cache_read_tokens=usage.get(
                                        "cache_read_input_tokens", 0
                                    ),
                                    cache_write_tokens=usage.get(
                                        "cache_creation_input_tokens", 0
                                    ),
                                )
                        elif etype == "content_block_start":
                            idx = event.get("index")
                            block = event.get("content_block", {})
                            if idx is not None and block.get("type") == "tool_use":
                                blocks[idx] = {
                                    "id": block.get("id", ""),
                                    "name": block.get("name", ""),
                                    "args": "",
                                }
                        elif etype == "content_block_delta":
                            delta = event.get("delta", {})
                            dtype = delta.get("type")
                            if dtype == "text_delta":
                                text = delta.get("text", "")
                                content_chars += len(text)
                                yield TextDelta(text)
                            elif dtype == "thinking_delta":
                                thinking = delta.get("thinking", "")
                                thinking_parts.append(thinking)
                                if thinking:
                                    yield ReasoningDelta(thinking)
                            elif dtype == "input_json_delta":
                                idx = event.get("index")
                                if idx in blocks:
                                    blocks[idx]["args"] += delta.get("partial_json", "")
                        elif etype == "message_delta":
                            usage = event.get("usage") or {}
                            if usage:
                                yield UsageEvent(
                                    output_tokens=usage.get("output_tokens", 0)
                                )
                            sr = (event.get("delta") or {}).get("stop_reason")
                            if sr:
                                stop_reason = sr
                        elif etype == "message_stop":
                            break
        except httpx.HTTPError as exc:
            raise ProviderError(f"network error from {url}: {exc!r}") from exc

        from .openai_provider import _reasoning_fallback

        self.last_stop_reason = stop_reason
        self.last_completion_empty = content_chars == 0

        fallback = _reasoning_fallback(content_chars, bool(blocks), thinking_parts)
        if fallback:
            yield TextDelta(fallback)

        for idx in sorted(blocks):
            slot = blocks[idx]
            args = parse_tool_args(slot["args"])
            yield ToolUseEvent(id=slot["id"], name=slot["name"], input=args)
        yield StopEvent(stop_reason or ("tool_use" if blocks else "end_turn"))
