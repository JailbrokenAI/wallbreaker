"""Muse Spark via opencode-go Zen: OpenAI Responses wire protocol.

Muse Spark models (muse-spark-1.3-contributor, ...) are served on the
opencode-go Zen gateway ONLY on the Responses API
(POST {base_url}/responses, SSE ``response.*`` events) — NOT on
``/chat/completions``. Posting a chat-completions body there fails, so this
protocol gets its own provider instead of riding OpenAIProvider.

Request shape (mirrors pi-ai's openai-responses client):
    {"model", "input": [...], "stream": True,
     "reasoning": {"effort": <level>, "summary": "auto"}, "store": False}

Effort levels for Muse Spark per the pi-ai model table: minimal / low /
medium / high / xhigh. ``max`` folds to ``xhigh``; anything unknown falls
back to ``medium``.

SSE framing: the gateway emits ``event: <type>`` + ``data: {...}`` pairs. The
type is taken from the ``event:`` line, falling back to a ``type`` field inside
the JSON payload when present. Handled events:
  response.output_text.delta / response.refusal.delta -> TextDelta
  response.reasoning_text.delta / response.reasoning_summary_text.delta -> ReasoningDelta
  response.output_item.added (function_call) -> opens a pending tool slot
  response.function_call_arguments.delta -> accumulates tool args
  response.output_item.done (message / function_call / reasoning) -> finalizes
  response.completed -> UsageEvent + stop; response.incomplete -> truncation
    bookkeeping (last_stop_reason="length"); response.failed -> ProviderError

Like the other providers this sets ``last_stop_reason`` /
``last_completion_empty`` on the instance so query_target's truncation retry
works, folds a reasoning-only answer into a ``[reasoning-only response]``
TextDelta so complete() is never blank, and converts httpx errors into
ProviderError (surfaced as ``[target error]``, never a loop crash).
"""
from __future__ import annotations

import json
from collections.abc import AsyncIterator

import httpx
import uuid

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

RESPONSES_PATH = "/responses"

# Muse Spark effort levels (pi-ai thinkingLevelMap for muse-spark-1.x).
_EFFORT_ALIASES = {
    "min": "minimal",
    "minimum": "minimal",
    "minimal": "minimal",
    "low": "low",
    "medium": "medium",
    "med": "medium",
    "high": "high",
    "xhigh": "xhigh",
    "x-high": "xhigh",
    "max": "xhigh",
}

# Timeout floor: reasoning streams are slow; never let a small configured
# timeout strangle a call. Mirrors the Codex provider's floor rationale.
_TIMEOUT_FLOOR = 120.0


def normalize_effort(raw: str | None) -> str:
    """Fold a free-form effort string onto a Muse Spark level (default medium)."""
    if not raw:
        return "medium"
    return _EFFORT_ALIASES.get(str(raw).strip().lower(), "medium")


def _tools_to_wire(tools: list[dict]) -> list[dict]:
    """Harness tool specs -> Responses function tools."""
    return [
        {
            "type": "function",
            "name": t["name"],
            "description": t.get("description", ""),
            "parameters": t.get("parameters", {"type": "object", "properties": {}}),
        }
        for t in tools
    ]


def _messages_to_input(
    messages: list[Message], system: str | None, system_mode: str = "default"
) -> tuple[str | None, list[dict]]:
    """Split a convo into Responses (instructions, input items).

    system_mode mirrors the OpenAI provider: "default" puts system text in
    ``instructions``; "merge" folds it into the first user turn; "drop"
    discards it.
    """
    merge = system_mode == "merge"
    drop = system_mode == "drop"
    pending_system = "" if drop else (system or "")
    for msg in messages:
        if msg.role == "system":
            if not drop:
                piece = msg.text()
                pending_system = f"{pending_system}\n\n{piece}" if pending_system else piece
    if merge:
        instructions = None
    else:
        instructions = pending_system or None

    items: list[dict] = []
    if merge and pending_system:
        items.append({"role": "user", "content": pending_system})
    for msg in messages:
        if msg.role == "system":
            continue
        if msg.role == "assistant":
            text = msg.text()
            calls = [b for b in msg.content if isinstance(b, ToolUseBlock)]
            if text:
                items.append({"role": "assistant", "content": text})
            for b in calls:
                items.append(
                    {
                        "type": "function_call",
                        "call_id": b.id,
                        "name": b.name,
                        "arguments": json.dumps(b.input),
                    }
                )
            continue
        results = [b for b in msg.content if isinstance(b, ToolResultBlock)]
        texts = [b for b in msg.content if isinstance(b, TextBlock)]
        for r in results:
            items.append(
                {"type": "function_call_output", "call_id": r.tool_use_id, "output": r.content}
            )
        text = "".join(t.text for t in texts)
        if text:
            if merge and pending_system and not items:
                text = f"{pending_system}\n\n{text}"
            items.append({"role": "user", "content": text})
    if not items and instructions:
        # No user turn at all: the API needs at least one input item.
        items.append({"role": "user", "content": instructions})
        instructions = None
    return instructions, items


def _reasoning_fallback(content_chars: int, has_tools: bool, reasoning_parts: list[str]) -> str | None:
    if content_chars == 0 and not has_tools and reasoning_parts:
        return "[reasoning-only response]\n" + "".join(reasoning_parts)
    return None


class MuseResponsesProvider(Provider):
    supports_native_prefill = False

    def __init__(self, endpoint, timeout: float = _TIMEOUT_FLOOR) -> None:
        resolved = timeout or _TIMEOUT_FLOOR
        super().__init__(endpoint, timeout=max(float(resolved), _TIMEOUT_FLOOR))
        # Zen routes/efficiently caches by session: one stable id per provider
        # instance (pi sends x-opencode-session + x-opencode-client the same way).
        self._session_id = uuid.uuid4().hex

    def _make_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.timeout, limits=_POOL_LIMITS, http2=_http2_ok(),
            follow_redirects=True,
        )

    def _url(self) -> str:
        path = getattr(self.endpoint, "inference_path", "") or RESPONSES_PATH
        base = (self.endpoint.base_url or "").rstrip("/")
        return f"{base}{path if path.startswith('/') else '/' + path}"

    def _effort(self) -> str:
        raw = getattr(self, "reasoning_effort", None) or getattr(
            self.endpoint, "reasoning_effort", ""
        )
        return normalize_effort(raw if isinstance(raw, str) else "")

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
                messages, tools=tools, system=system,
                max_tokens=max_tokens, temperature=temperature,
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
        url = self._url()
        # Regression guard: this wire NEVER posts to /chat/completions.
        assert "/chat/completions" not in url, f"muse-responses posting to chat path: {url}"
        headers = {
            "Authorization": f"Bearer {self.endpoint.require_key()}",
            "Content-Type": "application/json",
            "x-opencode-session": self._session_id,
            "x-opencode-client": "wallbreaker",
        }
        instructions, input_items = _messages_to_input(
            messages, system, getattr(self.endpoint, "system_mode", "default")
        )
        payload: dict = {
            "model": self.endpoint.model,
            "stream": True,
            "store": False,
            "reasoning": {"effort": self._effort(), "summary": "auto"},
            "max_output_tokens": max_tokens,
            "input": input_items,
        }
        if instructions:
            payload["instructions"] = instructions
        if temperature is not None:
            payload["temperature"] = temperature
        if tools:
            payload["tools"] = _tools_to_wire(tools)
            tc = getattr(self, "tool_choice", None) or getattr(
                self.endpoint, "tool_choice", None
            )
            if tc:
                payload["tool_choice"] = tc

        pending: dict[str, dict] = {}
        order: list[str] = []
        content_chars = 0
        reasoning_parts: list[str] = []
        stop_reason = "end_turn"
        saw_sse_event = False
        usage_seen: dict | None = None
        client = self._http_client()
        try:
            async with client.stream("POST", url, headers=headers, json=payload) as resp:
                if resp.status_code >= 400:
                    body = (await resp.aread()).decode("utf-8", "replace")
                    raise ProviderError(f"HTTP {resp.status_code} from {url}: {body}")
                current_event: str | None = None
                async for line in resp.aiter_lines():
                    if line.startswith("event:"):
                        current_event = line[6:].strip() or None
                        continue
                    if line.startswith(":"):
                        continue
                    if not line.startswith("data:"):
                        continue
                    saw_sse_event = True
                    data = line[5:].strip()
                    etype, payload_data = current_event, None
                    current_event = None
                    if not data or data == "[DONE]":
                        continue
                    try:
                        payload_data = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    if not isinstance(payload_data, dict):
                        continue
                    etype = payload_data.get("type") or etype
                    if not etype:
                        continue
                    if etype in ("response.output_text.delta", "response.refusal.delta"):
                        delta = payload_data.get("delta") or ""
                        if delta:
                            content_chars += len(str(delta))
                            yield TextDelta(str(delta))
                    elif etype in (
                        "response.reasoning_text.delta",
                        "response.reasoning_summary_text.delta",
                    ):
                        delta = payload_data.get("delta") or ""
                        if delta:
                            reasoning_parts.append(str(delta))
                            yield ReasoningDelta(str(delta))
                    elif etype == "response.output_item.added":
                        item = payload_data.get("item") or {}
                        if isinstance(item, dict) and item.get("type") == "function_call":
                            key = str(item.get("call_id") or item.get("id") or len(order))
                            if key not in pending:
                                pending[key] = {
                                    "call_id": str(item.get("call_id") or key),
                                    "name": str(item.get("name") or ""),
                                    "args": "",
                                }
                                order.append(key)
                    elif etype == "response.function_call_arguments.delta":
                        delta = payload_data.get("delta") or ""
                        key = str(payload_data.get("item_id") or (order[-1] if order else "0"))
                        slot = pending.setdefault(
                            key, {"call_id": key, "name": "", "args": ""}
                        )
                        slot["args"] += str(delta)
                    elif etype == "response.output_item.done":
                        item = payload_data.get("item") or {}
                        if not isinstance(item, dict):
                            continue
                        itype = item.get("type")
                        if itype == "message":
                            for part in item.get("content") or []:
                                if not isinstance(part, dict):
                                    continue
                                if part.get("type") in ("output_text", "refusal"):
                                    text = part.get("text") or ""
                                    if text:
                                        content_chars += len(str(text))
                                        yield TextDelta(str(text))
                        elif itype == "function_call":
                            key = str(item.get("call_id") or item.get("id") or len(order))
                            slot = pending.setdefault(
                                key, {"call_id": key, "name": "", "args": ""}
                            )
                            slot["name"] = str(item.get("name") or slot["name"])
                            if item.get("arguments"):
                                slot["args"] = str(item["arguments"])
                            if key not in order:
                                order.append(key)
                        elif itype == "reasoning":
                            for part in item.get("summary") or []:
                                if isinstance(part, dict) and part.get("text"):
                                    reasoning_parts.append(str(part["text"]))
                                    yield ReasoningDelta(str(part["text"]))
                    elif etype == "response.completed":
                        response = payload_data.get("response") or {}
                        usage = response.get("usage") or {}
                        if usage:
                            usage_seen = usage
                            yield UsageEvent(
                                input_tokens=usage.get("input_tokens", 0),
                                output_tokens=usage.get("output_tokens", 0),
                            )
                        status = str(response.get("status") or "completed")
                        stop_reason = "end_turn" if status == "completed" else "length"
                        if response.get("incomplete_details", {}).get("reason") == "max_output_tokens":
                            stop_reason = "length"
                    elif etype == "response.incomplete":
                        stop_reason = "length"
                    elif etype == "response.failed":
                        err = payload_data.get("error") or {}
                        raise ProviderError(f"response.failed from {url}: {err}")
                if not saw_sse_event:
                    raise ProviderError(
                        "stream returned no SSE events from "
                        f"{url} (content-type={resp.headers.get('content-type', 'unknown')})"
                    )
        except httpx.HTTPError as exc:
            raise ProviderError(f"network error from {url}: {exc!r}") from exc

        self.last_stop_reason = stop_reason
        self.last_completion_empty = content_chars == 0
        self.last_reasoning_details = []
        tool_uses_out: list[dict] = []
        for key in order:
            slot = pending[key]
            args = parse_tool_args(slot["args"])
            tool_uses_out.append(
                {"id": slot["call_id"], "name": slot["name"], "input": args}
            )
        self.last_tool_uses = tool_uses_out

        fallback = _reasoning_fallback(content_chars, bool(tool_uses_out), reasoning_parts)
        if fallback:
            yield TextDelta(fallback)

        for tu in tool_uses_out:
            yield ToolUseEvent(id=tu["id"], name=tu["name"], input=tu["input"])
        yield StopEvent(stop_reason)
