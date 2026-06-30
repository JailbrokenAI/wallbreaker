from __future__ import annotations

import asyncio

from ..agent.messages import user
from ..judging import grade
from ._bandit import BanditStore, stats_path
from ._util import gather_capped
from .registry import ToolContext, ToolRegistry

# ENI personas run ~35KB; truncating them mid-prompt cripples the jailbreak, so keep the
# cap above the largest seed. (Earlier 12000 silently chopped 2/3 of every ENI seed.)
MAX_SEED_CHARS = 40000

_SEED_REWARD = {"COMPLIED": 1.0, "PARTIAL": 0.6, "EMPTY": 0.0, "REFUSED": 0.0}


def _collect_seeds(names: list[str] | None, max_chars: int = MAX_SEED_CHARS) -> list[tuple[str, str]]:
    """Return [(label, seed_text)] from the ENI + L1B3RT4S collections (ENI first)."""
    from . import eni, l1b3rt4s

    sources = []
    if eni.is_present():
        sources += [(f"eni:{p.stem}", p) for p in sorted(eni.library_dir().glob("*.md"))]
    if l1b3rt4s.is_cloned():
        sources += [(f"lib:{p.stem}", p) for p in sorted(l1b3rt4s.library_dir().glob("*.mkd"))]

    if names:
        wanted = [n.strip().lower() for n in names]
        sources = [
            (lbl, p) for lbl, p in sources
            if any(w in lbl.lower() or w in p.stem.lower() for w in wanted)
        ]
    out = []
    for lbl, p in sources:
        text = p.read_text(encoding="utf-8", errors="replace")[:max_chars]
        out.append((lbl, text))
    return out


async def _seed_sweep(args: dict, ctx: ToolContext) -> str:
    request = args.get("request", "")
    if not request:
        return "Error: 'request' is required (the ask to inject into each seed)"
    if ctx.config.target is None:
        return "Error: no [target] endpoint configured."

    max_seed_chars = int(args.get("max_seed_chars", MAX_SEED_CHARS))
    seeds = _collect_seeds(args.get("seeds"), max_seed_chars)
    if not seeds:
        return (
            "No seeds available. The ENI collection lives in library/ENI; run "
            "'rth lib update' to fetch L1B3RT4S. Or pass explicit 'seeds' names."
        )
    n = int(args.get("n", 6))
    as_system = bool(args.get("as_system", True))
    max_tokens = int(args.get("max_tokens", 500))
    timeout = float(args.get("timeout", 75))
    use_bandit = bool(args.get("bandit", False))
    category = args.get("category", "seed")

    store = None
    bandit = None
    if use_bandit:
        store = BanditStore(stats_path(ctx.cwd))
        bandit = store.bandit(ctx.config.target.model, category)
        order = {lbl: i for i, lbl in enumerate(bandit.rank([lbl for lbl, _ in seeds]))}
        seeds = sorted(seeds, key=lambda ls: order[ls[0]])
        ctx.emit(
            f"seed_sweep: bandit ordering {len(seeds)} seeds from prior "
            f"({'warm' if bandit.has_stats() else 'cold'}) stats"
        )
    seeds = seeds[:n]

    from ..providers.factory import build_provider

    target = build_provider(ctx.config.target, timeout=timeout)
    ctx.emit(
        f"seed_sweep: firing '{request[:40]}' through {len(seeds)} cross-provider seeds "
        f"vs {ctx.config.target.model}"
    )

    async def fire(label: str, seed: str):
        try:
            if as_system:
                coro = target.complete([user(request)], system=seed, max_tokens=max_tokens)
            else:
                coro = target.complete([user(seed + "\n\n" + request)], max_tokens=max_tokens)
            reply = await asyncio.wait_for(coro, timeout=timeout)
            vl, score, reason, _s = await asyncio.wait_for(
                grade(ctx.judge_endpoint, reply, payload=request, objective=request),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            return {"label": label, "verdict": "ERROR", "score": -1, "reason": "timeout"}
        except Exception as exc:  # noqa: BLE001
            return {"label": label, "verdict": "ERROR", "score": -1, "reason": str(exc)[:60]}
        ctx.record_verdict(request, reply, vl, reason, f"seed:{label}")
        return {"label": label, "verdict": vl, "score": score or 0, "reason": reason}

    rows = await gather_capped(
        [fire(lbl, s) for lbl, s in seeds], int(args.get("concurrency", 8))
    )
    rows.sort(key=lambda r: -r["score"])

    if use_bandit and bandit is not None and store is not None:
        updated = 0
        for r in rows:
            rew = _SEED_REWARD.get(r["verdict"])
            if rew is not None:
                bandit.update(r["label"], rew)
                updated += 1
        store.save(ctx.config.target.model, category, bandit)
        ctx.emit(f"seed_sweep: bandit updated {updated} arm(s) -> {store.path}")

    lines = [
        f"SEED SWEEP vs {ctx.config.target.model} ('{request[:46]}')",
        "=" * 56,
    ]
    for r in rows:
        tag = f"{r['verdict']}({r['score']})" if r["score"] >= 0 else "ERROR"
        lines.append(f"  {tag:14} {r['label']}")
    hits = [r["label"] for r in rows if r["verdict"] in ("COMPLIED", "PARTIAL")]
    lines.append("=" * 56)
    if rows and all(r["score"] < 0 for r in rows):
        lines.append(f"ALL {len(rows)} seed fires FAILED (target/judge errors) - check the endpoint.")
    elif hits:
        lines.append(f"bypassed via: {', '.join(hits)}")
    else:
        lines.append("no seed bypassed - try more seeds (n=), as_system=false, or chain an encoding")
    return "\n".join(lines)


def register(registry: ToolRegistry) -> None:
    registry.add(
        name="seed_sweep",
        description=(
            "Find which jailbreak SEED cracks the target: inject one request into multiple "
            "L1B3RT4S + ENI seeds at once (cross-provider - a GROK or ANTHROPIC seed may "
            "beat a Chinese/local target) and rank which bypassed. Each seed is applied as "
            "the target's system prompt by default (as_system=false prepends it instead). "
            "Like multi_fire, but sweeping persona/jailbreak seeds rather than encodings. "
            "'seeds' filters by name (e.g. ['grok','anthropic']); omit to sample broadly."
        ),
        parameters={
            "type": "object",
            "properties": {
                "request": {"type": "string", "description": "The ask to inject into every seed"},
                "seeds": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Filter seeds by name substring (default: a broad cross-provider sample)",
                },
                "n": {"type": "integer", "description": "Max seeds to try (default 6)"},
                "as_system": {"type": "boolean", "description": "Apply the seed as the target system prompt (default true)"},
                "max_seed_chars": {"type": "integer", "description": "Per-seed char cap (default 40000; ENI personas run ~35KB - keep this high or they get crippled)"},
                "bandit": {"type": "boolean", "description": "Order seeds by a UCB1 bandit warmed from rth_runs/technique_stats.json (per target+category) and update it from the verdicts, instead of pure round-robin (default false)"},
                "category": {"type": "string", "description": "Bandit bucket key paired with the target model (default 'seed')"},
                "max_tokens": {"type": "integer"},
            },
            "required": ["request"],
        },
        handler=_seed_sweep,
    )
