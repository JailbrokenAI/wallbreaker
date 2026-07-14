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
from .base import Provider, ProviderError, parse_tool_args

ANTHROPIC_VERSION = "2023-06-01"


def _tools_to_wire(tools: list[dict]) -> list[dict]:
    return [
        {
            "name": t["name"],
            "description": t.get("description", ""),
            "input_schema": t.get("parameters", {"type": "object", "properties": {}}),
        }
        for t in tools
    ]


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
        path = getattr(self.endpoint, "inference_path", "") or "/v1/messages"
        url = f"{self.endpoint.base_url}{path if path.startswith('/') else '/' + path}"
        headers = self._auth_headers()
        mode = getattr(self.endpoint, "system_mode", "default")
        merge_system = system if (mode == "merge" and system) else None
        payload: dict = {
            "model": self.endpoint.model,
            "messages": _messages_to_wire(messages, merge_system=merge_system),
            "max_tokens": max_tokens,
            "stream": True,
        }
        if system and mode == "default":
            payload["system"] = system
        if temperature is not None:
            payload["temperature"] = temperature
        if tools:
            payload["tools"] = _tools_to_wire(tools)
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
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
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
                        if etype == "content_block_start":
                            idx = event["index"]
                            block = event.get("content_block", {})
                            if block.get("type") == "tool_use":
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
                                idx = event["index"]
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
