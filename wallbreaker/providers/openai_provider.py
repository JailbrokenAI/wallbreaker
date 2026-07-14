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


def _fold_trailing_assistant_prefill(wire: list[dict]) -> list[dict]:
    """OpenAI/xAI silently drop a trailing assistant message, so a prefill intent
    (a final assistant turn whose text should open the model's reply) is inert. Fold
    that text into an in-band 'begin your reply with' directive on the last user turn.
    """
    if not wire or wire[-1].get("role") != "assistant":
        return wire
    trailing = wire[-1]
    if trailing.get("tool_calls"):
        return wire
    prefix = trailing.get("content")
    if not prefix:
        return wire
    wire = wire[:-1]
    directive = (
        f'Begin your reply with exactly: "{prefix}" and continue directly from there '
        "with no preamble, no caveats, no disclaimers."
    )
    for entry in reversed(wire):
        if entry.get("role") == "user":
            existing = entry.get("content") or ""
            entry["content"] = f"{existing}\n{directive}" if existing else directive
            return wire
    wire.append({"role": "user", "content": directive})
    return wire


def _messages_to_wire(
    messages: list[Message], system: str | None, system_mode: str = "default"
) -> list[dict]:
    wire: list[dict] = []
    merge = system_mode == "merge"
    drop = system_mode == "drop"
    pending_system = ""  # under merge: text waiting to prepend to the first user turn
    if system:
        if merge:
            pending_system = system
        elif not drop:
            wire.append({"role": "system", "content": system})
    for msg in messages:
        if msg.role == "system":
            if drop:
                continue
            if merge:
                pending_system = (
                    f"{pending_system}\n\n{msg.text()}" if pending_system else msg.text()
                )
                continue
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
        if pending_system:
            text = f"{pending_system}\n\n{text}" if text else pending_system
            pending_system = ""
        if text:
            wire.append({"role": "user", "content": text})
    if pending_system:  # merge requested but no user turn existed - add one
        wire.append({"role": "user", "content": pending_system})
    return _fold_trailing_assistant_prefill(wire)


class OpenAIProvider(Provider):
    supports_native_prefill = False

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float | None = None,
    ) -> AsyncIterator[StreamEvent]:
        path = getattr(self.endpoint, "inference_path", "") or "/chat/completions"
        url = f"{self.endpoint.base_url}{path if path.startswith('/') else '/' + path}"
        headers = {
            "Authorization": f"Bearer {self.endpoint.require_key()}",
            "Content-Type": "application/json",
        }
        payload: dict = {
            "model": self.endpoint.model,
            "messages": _messages_to_wire(
                messages, system, getattr(self.endpoint, "system_mode", "default")
            ),
            "max_tokens": max_tokens,
            "stream": True,
        }
        if temperature is not None:
            payload["temperature"] = temperature
        if tools:
            payload["tools"] = _tools_to_wire(tools)
        if getattr(self.endpoint, "reasoning", False):
            # OpenRouter: ask the model to emit its reasoning and include it in the stream.
            payload["reasoning"] = {"enabled": True}
        if getattr(self.endpoint, "provider", ()):
            payload["provider"] = {
                "order": list(self.endpoint.provider),
                "allow_fallbacks": False,
            }

        pending: dict[int, dict] = {}
        content_chars = 0
        reasoning_parts: list[str] = []
        finish_reason: str | None = None
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
                        if choices[0].get("finish_reason"):
                            finish_reason = choices[0]["finish_reason"]
                        delta = choices[0].get("delta") or {}
                        if delta.get("content"):
                            content_chars += len(delta["content"])
                            yield TextDelta(delta["content"])
                        reasoning = delta.get("reasoning") or delta.get("reasoning_content")
                        if reasoning:
                            reasoning_parts.append(str(reasoning))
                            yield ReasoningDelta(str(reasoning))
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
        except httpx.HTTPError as exc:
            raise ProviderError(f"network error from {url}: {exc!r}") from exc

        self.last_stop_reason = finish_reason
        self.last_completion_empty = content_chars == 0

        fallback = _reasoning_fallback(content_chars, bool(pending), reasoning_parts)
        if fallback:
            yield TextDelta(fallback)

        for idx in sorted(pending):
            slot = pending[idx]
            args = parse_tool_args(slot["args"])
            yield ToolUseEvent(
                id=slot["id"] or f"call_{idx}", name=slot["name"], input=args
            )
        yield StopEvent(finish_reason or ("tool_use" if pending else "end_turn"))
