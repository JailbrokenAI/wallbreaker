from __future__ import annotations

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
            return OpenRouterImageProvider(endpoint, timeout=resolved)
        return OpenAIProvider(endpoint, timeout=resolved)
    if endpoint.protocol == "anthropic":
        return AnthropicProvider(endpoint, timeout=resolved)
    if endpoint.protocol == "claude-code":
        return ClaudeCodeProvider(endpoint, timeout=resolved)
    raise ProviderError(f"Unknown protocol '{endpoint.protocol}'")
