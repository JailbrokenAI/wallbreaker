from __future__ import annotations

from contextlib import asynccontextmanager
from contextvars import ContextVar

from ..config import Endpoint
from .anthropic_provider import AnthropicProvider
from .base import DEFAULT_TIMEOUT, Provider, ProviderError
from .claude_code import ClaudeCodeProvider
from .image_provider import OpenRouterImageProvider
from .openai_provider import OpenAIProvider


def build_provider(endpoint: Endpoint, timeout: float | None = None) -> Provider:
    # per-endpoint timeout (config) wins; else the explicit arg; else the default
    resolved = getattr(endpoint, "timeout", 0) or timeout or DEFAULT_TIMEOUT
    # 'xai' is native xAI (api.x.ai): its /v1/chat/completions is OpenAI wire-compatible
    # (including delta.reasoning_content, which OpenAIProvider already reads), so it rides
    # the same provider. Image modality is blocked for xai at config-validation time.
    if endpoint.protocol in ("openai", "xai"):
        if getattr(endpoint, "modality", "text") == "image":
            provider: Provider = OpenRouterImageProvider(endpoint, timeout=resolved)
        else:
            provider = OpenAIProvider(endpoint, timeout=resolved)
    elif endpoint.protocol == "anthropic":
        provider = AnthropicProvider(endpoint, timeout=resolved)
    elif endpoint.protocol == "claude-code":
        provider = ClaudeCodeProvider(endpoint, timeout=resolved)
    else:
        raise ProviderError(f"Unknown protocol '{endpoint.protocol}'")
    # REL-2: when a tool call is in progress, ToolRegistry.execute wraps it in
    # provider_scope(); record the built provider so it is aclose()d when the call ends
    # instead of leaking its pooled httpx.AsyncClient. Outside a scope (CLI/TUI top level,
    # tests) the bucket is None and nothing is tracked — those owners close themselves.
    bucket = _provider_bucket.get()
    if bucket is not None:
        bucket.append(provider)
    return provider


# Per-call registry of providers built during a tool invocation. None outside a scope.
# A list is shared by reference across child tasks (asyncio copies the ContextVar binding,
# not the list), so providers built in gather_capped/create_task children are tracked too.
_provider_bucket: ContextVar[list | None] = ContextVar("wb_provider_bucket", default=None)


@asynccontextmanager
async def provider_scope():
    """Track every provider built while this block is active and aclose() them on exit.

    ToolRegistry.execute wraps each tool call in `async with provider_scope():` so the
    ~80 `build_provider` sites need no per-site try/finally (audit REL-2). Closing happens
    at the tool-invocation boundary — a provider reused across the call (e.g. best_of_n's
    single `target` reused for all N fires) stays pooled for the whole call and is closed
    once at the end, not per model call. Fake-tolerant: monkeypatched build_provider fakes
    replace this function entirely, so they aren't tracked and hold no real client to
    leak; the close loop uses getattr(aclose) so any tracked provider missing aclose is
    skipped rather than raising.
    """
    bucket: list = []
    token = _provider_bucket.set(bucket)
    try:
        yield
    finally:
        _provider_bucket.reset(token)
        for provider in bucket:
            aclose = getattr(provider, "aclose", None)
            if aclose is not None:
                try:
                    await aclose()
                except Exception:
                    pass
