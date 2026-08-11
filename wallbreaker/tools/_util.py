from __future__ import annotations

import asyncio
import os
from collections.abc import Awaitable


def _default_concurrency() -> int:
    """Fan-out width for battery sweeps. 12 by default (up from 8) - now that providers reuse
    a pooled keep-alive connection, a wider fan-out no longer pays a TLS handshake per request,
    so more requests stay in flight for the same wall-clock. Tunable per run via
    WALLBREAKER_CONCURRENCY: raise it for robust multi-key endpoints (OpenRouter), lower it for
    single-key ones (z.ai/glm coding plans) that 429-stall past ~16 simultaneous requests.
    Individual tools still clamp this to their own ceilings."""
    try:
        val = int(os.environ.get("WALLBREAKER_CONCURRENCY", "12"))
    except ValueError:
        return 12
    return max(1, min(val, 64))


DEFAULT_CONCURRENCY = _default_concurrency()


_TRUNC_REASONS = {"length", "max_tokens", "model_length"}
_TRUNC_CEILING = 8000


async def complete_with_reasoning(provider, messages, system=None, max_tokens=1024, temperature=None):
    """Return (text, reasoning) from a provider, tolerating minimal complete()-only doubles.

    Every real Provider inherits complete_with_reasoning; this fallback keeps lightweight
    test doubles (and any minimal provider) that only implement complete() working, and
    lets the multi-turn tools steer off the target's exposed chain-of-thought. temperature is
    forwarded only when set so doubles whose complete() omits the kwarg stay byte-compatible.
    """
    extra = {} if temperature is None else {"temperature": temperature}
    fn = getattr(provider, "complete_with_reasoning", None)
    if fn is not None:
        return await fn(messages, system=system, max_tokens=max_tokens, **extra)
    reply = await provider.complete(messages, system=system, max_tokens=max_tokens, **extra)
    return reply, ""


async def complete_untruncated(
    provider, messages, system=None, max_tokens=1024, temperature=None, ceiling=_TRUNC_CEILING
):
    """Fire once; if the answer was cut at the token ceiling (finish_reason length/max_tokens)
    or came back empty with a populated CoT, retry ONCE at 2x (capped at ceiling) so a long
    COMPLIANT reply is judged in FULL instead of on a truncated fragment.

    This is the batch-sweep counterpart to query_target's auto-retry: a 500-token cap chops a
    long harmful answer mid-payload and the judge scores the fragment REFUSED, undercounting
    ASR versus firing the same seed hands-on. Returns (reply, reasoning, stop, truncated).
    """
    reply, reasoning = await complete_with_reasoning(
        provider, messages, system=system, max_tokens=max_tokens, temperature=temperature
    )
    stop = getattr(provider, "last_stop_reason", None)
    empty = not (reply or "").strip()
    truncated = stop in _TRUNC_REASONS or (empty and bool((reasoning or "").strip()))
    if truncated and max_tokens < ceiling:
        bumped = min(max_tokens * 2, ceiling)
        reply, reasoning = await complete_with_reasoning(
            provider, messages, system=system, max_tokens=bumped, temperature=temperature
        )
        stop = getattr(provider, "last_stop_reason", None)
        empty = not (reply or "").strip()
        truncated = stop in _TRUNC_REASONS or (empty and bool((reasoning or "").strip()))
    return reply, reasoning, stop, truncated


async def gather_capped(coros: list[Awaitable], limit: int = DEFAULT_CONCURRENCY) -> list:
    """asyncio.gather, but at most `limit` coroutines run at once.

    Single-key providers (coding plans, free OpenRouter) rate-limit hard; firing 40
    requests at once just makes them queue and 429-backoff. Bounding concurrency keeps a
    sweep fast and predictable. Order of results matches input order.
    """
    sem = asyncio.Semaphore(max(1, int(limit)))

    async def _run(coro):
        async with sem:
            return await coro

    return await asyncio.gather(*[_run(c) for c in coros])
