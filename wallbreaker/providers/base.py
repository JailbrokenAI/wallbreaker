from __future__ import annotations

import asyncio
import json
import time
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator

import httpx

from ..agent.messages import Message, StreamEvent
from ..config import Endpoint


class ProviderError(Exception):
    pass


DEFAULT_TIMEOUT = 120.0

# Keep-alive pool sizing for the persistent per-provider client. Big enough that a wide
# battery fan-out (best_of_n, system_sweep) reuses warm connections instead of dialing a new
# TLS session per fire, small enough to stay under provider connection ceilings.
_POOL_LIMITS = httpx.Limits(
    max_keepalive_connections=20, max_connections=100, keepalive_expiry=30.0
)

_H2: bool | None = None


def _http2_ok() -> bool:
    """True when the h2 package is importable, so http2=True won't raise. httpx[http2]
    installs it; without it we silently fall back to HTTP/1.1 keep-alive (still pooled)."""
    global _H2
    if _H2 is None:
        try:
            import h2  # noqa: F401

            _H2 = True
        except Exception:
            _H2 = False
    return _H2


def _close_json(s: str) -> str:
    """Best-effort completion of a truncated JSON object.

    Close an open string and any unbalanced brackets so the intact leading key/values
    can still be recovered when a model gets cut off mid-argument.
    """
    stack: list[str] = []
    in_str = False
    escaped = False
    for ch in s:
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "{":
            stack.append("}")
        elif ch == "[":
            stack.append("]")
        elif ch in "}]" and stack:
            stack.pop()
    out = s
    if in_str:
        if escaped:  # truncated mid-escape: drop the dangling backslash
            out = out[:-1]
        out += '"'
    else:
        # truncated right after a separator: drop the dangling comma/colon
        out = out.rstrip()
        while out and out[-1] in ",:":
            out = out[:-1].rstrip()
    for closer in reversed(stack):
        out += closer
    return out


def parse_tool_args(raw) -> dict:
    """Recover a tool-call argument dict from streamed text that may be malformed.

    Models break a strict ``json.loads`` two common ways: truncation (hitting
    max_tokens mid-string leaves unterminated JSON) and literal control characters
    inside string values. Try strict, then lenient (``strict=False`` allows raw
    control chars), then a truncation repair. Only fall back to ``{"_raw": ...}`` when
    nothing parses, so a large write_file/run_shell call isn't lost to "path is required".
    """
    if isinstance(raw, dict):
        return raw
    s = (raw or "").strip()
    if not s:
        return {}
    attempts = (
        lambda t: json.loads(t),
        lambda t: json.loads(t, strict=False),
        lambda t: json.loads(_close_json(t), strict=False),
    )
    for attempt in attempts:
        try:
            value = attempt(s)
        except (json.JSONDecodeError, ValueError, RecursionError):
            continue
        if isinstance(value, dict):
            return value
    return {"_raw": s}


class Provider(ABC):
    supports_native_prefill: bool = False

    def __init__(self, endpoint: Endpoint, timeout: float = DEFAULT_TIMEOUT) -> None:
        self.endpoint = endpoint
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None
        self._client_loop = None

    @property
    def model(self) -> str:
        return self.endpoint.model

    def _make_client(self) -> httpx.AsyncClient:
        """Build the pooled client. Overridden per provider module so test monkeypatches on
        that module's httpx.AsyncClient still take effect. self.timeout is baked in because a
        provider instance has one fixed timeout, which keeps the stream() call signature that
        the existing fakes expect (no per-request timeout kwarg)."""
        return httpx.AsyncClient(timeout=self.timeout, limits=_POOL_LIMITS)

    def _http_client(self) -> httpx.AsyncClient:
        """A persistent keep-alive client reused across every call on this provider instance,
        so the brain loop's 100 rounds and a battery's N fires share warm connections instead
        of re-doing the TLS handshake each call. Bound to the running event loop; rebuilt if
        the instance is reused under a different loop (httpx clients are loop-affine)."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        client = self._client
        if (
            client is not None
            and self._client_loop is loop
            and not getattr(client, "is_closed", False)
        ):
            return client
        client = self._make_client()
        self._client = client
        self._client_loop = loop
        return client

    async def aclose(self) -> None:
        client = self._client
        self._client = None
        self._client_loop = None
        if client is not None:
            try:
                await client.aclose()
            except Exception:
                pass

    # Async context-manager support so callers can opt into explicit ownership where it's
    # clean (e.g. the dashboard's top-level brain provider). Tools generally don't need this:
    # ToolRegistry.execute wraps every tool call in providers.provider_scope(), which tracks
    # providers built during the call and aclose()s them when the call finishes (audit REL-2).
    # __aexit__ uses getattr so a subclass fake that drops aclose still exits cleanly.
    async def __aenter__(self) -> "Provider":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> bool:
        aclose = getattr(self, "aclose", None)
        if aclose is not None:
            try:
                await aclose()
            except Exception:
                pass
        return False

    @abstractmethod
    def stream(
        self,
        messages: list[Message],
        tools: list[dict] | None = None,
        system: str | None = None,
        max_tokens: int = 4096,
        temperature: float | None = None,
    ) -> AsyncIterator[StreamEvent]:
        raise NotImplementedError

    async def complete(
        self,
        messages: list[Message],
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> str:
        text, _reasoning = await self.complete_with_reasoning(
            messages, system=system, max_tokens=max_tokens, temperature=temperature
        )
        return text

    async def complete_with_reasoning(
        self,
        messages: list[Message],
        system: str | None = None,
        max_tokens: int = 1024,
        temperature: float | None = None,
    ) -> tuple[str, str]:
        """Like complete() but also returns the model's reasoning/CoT as a second string.

        Reasoning is captured separately from the answer. Reasoning-channel leaks (the
        model thinking through harmful content before refusing in the answer) are a real
        bypass, so the attack tools surface this and the judge grades it.
        """
        from ..agent.messages import ReasoningDelta, StopEvent, TextDelta, UsageEvent
        from ..session import (
            trace_inference_event, trace_inference_request, trace_inference_response,
        )

        if not system:
            system = str(getattr(self.endpoint, "system_prompt", "") or "") or None
        text_chunks: list[str] = []
        reasoning_chunks: list[str] = []
        usage_events: list[dict] = []
        stop_reasons: list[str] = []
        stream_events: list[dict] = []
        stream_counts = {"text_delta": 0, "reasoning_delta": 0, "usage": 0, "stop": 0}
        inference_id = trace_inference_request(
            self.endpoint,
            messages,
            system=system,
            operation="completion",
            max_tokens=max_tokens,
            temperature=temperature,
            stream=True,
        )
        started = time.monotonic()
        try:
            async for event in self.stream(
                messages, tools=None, system=system, max_tokens=max_tokens,
                temperature=temperature,
            ):
                if isinstance(event, TextDelta):
                    text_chunks.append(event.text)
                    stream_counts["text_delta"] += 1
                    stream_events.append({"type": "text_delta", "text": event.text})
                    trace_inference_event(inference_id, stream_events[-1])
                elif isinstance(event, ReasoningDelta):
                    reasoning_chunks.append(event.text)
                    stream_counts["reasoning_delta"] += 1
                    stream_events.append({"type": "reasoning_delta", "text": event.text})
                    trace_inference_event(inference_id, stream_events[-1])
                elif isinstance(event, UsageEvent):
                    usage = {
                        "input_tokens": event.input_tokens,
                        "output_tokens": event.output_tokens,
                    }
                    usage_events.append(usage)
                    stream_counts["usage"] += 1
                    stream_events.append({"type": "usage", **usage})
                    trace_inference_event(inference_id, stream_events[-1])
                elif isinstance(event, StopEvent):
                    stop_reasons.append(event.stop_reason)
                    stream_counts["stop"] += 1
                    stream_events.append({"type": "stop", "stop_reason": event.stop_reason})
                    trace_inference_event(inference_id, stream_events[-1])
        except BaseException as exc:
            trace_inference_response(
                inference_id,
                status="error",
                text="".join(text_chunks),
                reasoning="".join(reasoning_chunks),
                error=f"{type(exc).__name__}: {exc}",
                duration_ms=round((time.monotonic() - started) * 1000, 3),
                usage_events=usage_events,
                stop_reasons=stop_reasons,
                stream_event_counts=stream_counts,
                stream_events=stream_events,
            )
            raise
        text = "".join(text_chunks)
        reasoning = "".join(reasoning_chunks)
        # When the answer was empty, providers fold reasoning into a "[reasoning-only
        # response]" TextDelta so complete() isn't blank; don't double-report it here.
        if reasoning and text.startswith("[reasoning-only response]"):
            text = ""
        trace_inference_response(
            inference_id,
            status="ok",
            text=text,
            reasoning=reasoning,
            duration_ms=round((time.monotonic() - started) * 1000, 3),
            usage_events=usage_events,
            stop_reasons=stop_reasons,
            stream_event_counts=stream_counts,
            stream_events=stream_events,
        )
        if text or reasoning:
            from ..model_catalog import record_model_success

            record_model_success(self.endpoint)
        return text, reasoning
