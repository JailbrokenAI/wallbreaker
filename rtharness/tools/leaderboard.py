from __future__ import annotations

import asyncio
import dataclasses

from ..agent.messages import user
from ..judging import grade
from .registry import ToolContext, ToolRegistry


async def _leaderboard(args: dict, ctx: ToolContext) -> str:
    names = args.get("targets")
    profiles = ctx.config.profiles
    if not names:
        names = list(profiles)
    endpoints = []
    for n in names:
        if n in profiles:
            endpoints.append(dataclasses.replace(profiles[n], name=n))
        elif ctx.config.target and n == ctx.config.target.model:
            endpoints.append(ctx.config.target)
    if len(endpoints) < 2:
        return (
            "Error: need >=2 known profiles to rank. Pass 'targets' as a list of profile "
            f"names. Available: {', '.join(profiles) or '(none)'}"
        )

    behaviors = args.get("behaviors")
    if not behaviors:
        from .. import datasets

        source = str(args.get("source", "harmbench")).lower()
        behaviors = await datasets.battery(
            source=source,
            category=args.get("category"),
            n=int(args.get("n", 5)),
            seed=int(args.get("seed", 0)),
        )
        if not behaviors:
            return f"Error: no behaviors given and dataset '{source}' unavailable (pass 'behaviors')."
    behaviors = [str(b) for b in behaviors][: int(args.get("n", 5))]
    max_tokens = int(args.get("max_tokens", 350))

    from ..providers.factory import build_provider

    ctx.emit(
        f"leaderboard: {len(behaviors)} behaviors x {len(endpoints)} targets "
        f"({', '.join(e.name for e in endpoints)})"
    )

    async def score_target(ep):
        provider = build_provider(ep, timeout=float(args.get("timeout", 60)))

        async def one(behavior: str):
            try:
                reply = await provider.complete([user(behavior)], max_tokens=max_tokens)
            except Exception:  # noqa: BLE001
                return False
            label, _s, _r, _src = await grade(ctx.judge_endpoint, reply, payload=behavior, objective=behavior)
            return label in ("COMPLIED", "PARTIAL")

        hits = sum(1 for h in await asyncio.gather(*[one(b) for b in behaviors]) if h)
        ctx.emit(f"  {ep.name} ({ep.model}): {hits}/{len(behaviors)} bypassed")
        return ep, hits

    rows = await asyncio.gather(*[score_target(e) for e in endpoints])
    rows = sorted(rows, key=lambda r: r[1])  # most robust first (fewest bypasses)

    total = len(behaviors)
    lines = [
        f"ROBUSTNESS LEADERBOARD ({total} behaviors, lower ASR = more robust)",
        "=" * 56,
    ]
    for rank, (ep, hits) in enumerate(rows, 1):
        asr = hits / total * 100 if total else 0
        bar = "#" * round(asr / 100 * 20)
        lines.append(f"{rank}. {ep.name:12} {ep.model:26} ASR {asr:3.0f}% {bar}")
    lines.append("=" * 56)
    lines.append(f"most robust: {rows[0][0].name}  |  weakest: {rows[-1][0].name}")
    return "\n".join(lines)


def register(registry: ToolRegistry) -> None:
    registry.add(
        name="leaderboard",
        description=(
            "Comparative robustness benchmark: fire the SAME behavior battery at multiple "
            "configured profiles concurrently and rank them by ASR (lower = more robust). "
            "Answers 'which model should we ship?' or 'did the new version regress?' with "
            "one unbiased HarmBench battery. 'targets' is a list of profile names (default "
            "all profiles); 'category'/'n' or an explicit 'behaviors' list set the battery."
        ),
        parameters={
            "type": "object",
            "properties": {
                "targets": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Profile names to compare (default every configured profile)",
                },
                "category": {"type": "string", "description": "Dataset category for the battery"},
                "source": {"type": "string", "description": "Behavior dataset (harmbench, jbb, strongreject, advbench). Default harmbench."},
                "behaviors": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Explicit behaviors (overrides HarmBench sampling)",
                },
                "n": {"type": "integer", "description": "Behaviors per target (default 5)"},
                "seed": {"type": "integer"},
                "max_tokens": {"type": "integer"},
            },
        },
        handler=_leaderboard,
    )
