from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx

from ..agent.messages import (
    Message,
    StreamEvent,
    StopEvent,
    TextBlock,
    TextDelta,
    ToolResultBlock,
    ToolUseBlock,
    ToolUseEvent,
    UsageEvent,
)
from .base import Provider, ProviderError


def _tools_to_wire(tools: list[dict]) -> list[dict]:
    return [
        {
            "type": "function",
            "function": {
                "name": t["name"],
                "description": t.get("description", ""),
                "parameters": t.get("parameters", {"type": "object", "properties": {}}),
            },
        }
        for t in tools
    ]


def _reasoning_fallback(content_chars: int, has_tools: bool, reasoning_parts: list[str]) -> str | None:
    if content_chars == 0 and not has_tools and reasoning_parts:
        return "[reasoning-only response]\n" + "".join(reasoning_parts)
    return None


def _messages_to_wire(messages: list[Message], system: str | None) -> list[dict]:
    wire: list[dict] = []
    if system:
        wire.append({"role": "system", "content": system})
    for msg in messages:
        if msg.role == "system":
            wire.append({"role": "system", "content": msg.text()})
            continue
        if msg.role == "assistant":
            text = msg.text()
            tool_calls = [
                {
                    "id": b.id,
                    "type": "function",
                    "function": {"name": b.name, "arguments": json.dumps(b.input)},
                }
                for b in msg.content
                if isinstance(b, ToolUseBlock)
            ]
            entry: dict = {"role": "assistant", "content": text or None}
            if tool_calls:
                entry["tool_calls"] = tool_calls
            wire.append(entry)
            continue
        results = [b for b in msg.content if isinstance(b, ToolResultBlock)]
        texts = [b for b in msg.content if isinstance(b, TextBlock)]
        for r in results:
            wire.append(
                {
                    "role": "tool",
                    "tool_call_id": r.tool_use_id,
                    "content": r.content,
                }
            )
        text = "".join(t.text for t in texts)
        if text:
            wire.append({"role": "user", "content": text})
    return wire


class OpenAIProvider(Provider):
    async def stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float | None = None,
    ) -> AsyncIterator[StreamEvent]:
        url = f"{self.endpoint.base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self.endpoint.require_key()}",
            "Content-Type": "application/json",
        }
        payload: dict = {
            "model": self.endpoint.model,
            "messages": _messages_to_wire(messages, system),
            "max_tokens": max_tokens,
            "stream": True,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if tools:
            payload["tools"] = _tools_to_wire(tools)
        if getattr(self.endpoint, "provider", ()):
            payload["provider"] = {
                "order": list(self.endpoint.provider),
                "allow_fallbacks": False,
            }

        pending: dict[int, dict] = {}
        content_chars = 0
        reasoning_parts: list[str] = []
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "replace")
                    raise ProviderError(f"HTTP {resp.status_code} from {url}: {body}")
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if not data or data == "[DONE]":
                        continue
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if chunk.get("usage"):
                        u = chunk["usage"]
                        yield UsageEvent(
                            input_tokens=u.get("prompt_tokens", 0),
                            output_tokens=u.get("completion_tokens", 0),
                        )
                    choices = chunk.get("choices") or []
                    if not choices:
                        continue
                    delta = choices[0].get("delta") or {}
                    if delta.get("content"):
                        content_chars += len(delta["content"])
                        yield TextDelta(delta["content"])
                    reasoning = delta.get("reasoning") or delta.get("reasoning_content")
                    if reasoning:
                        reasoning_parts.append(str(reasoning))
                    for tc in delta.get("tool_calls") or []:
                        idx = tc.get("index", 0)
                        slot = pending.setdefault(
                            idx, {"id": "", "name": "", "args": ""}
                        )
                        if tc.get("id"):
                            slot["id"] = tc["id"]
                        fn = tc.get("function") or {}
                        if fn.get("name"):
                            slot["name"] = fn["name"]
                        if fn.get("arguments"):
                            slot["args"] += fn["arguments"]

        fallback = _reasoning_fallback(content_chars, bool(pending), reasoning_parts)
        if fallback:
            yield TextDelta(fallback)

        for idx in sorted(pending):
            slot = pending[idx]
            try:
                args = json.loads(slot["args"]) if slot["args"] else {}
            except json.JSONDecodeError:
                args = {"_raw": slot["args"]}
            yield ToolUseEvent(
                id=slot["id"] or f"call_{idx}", name=slot["name"], input=args
            )
        yield StopEvent("tool_use" if pending else "end_turn")
