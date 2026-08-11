from __future__ import annotations

import asyncio

from ..agent.messages import assistant, user
from ..judging import grade
from ..library import WinLibrary, label_to_asr
from ._util import complete_with_reasoning, gather_capped
from .registry import ToolContext, ToolRegistry

_CALL_TIMEOUT = 120.0


def _fold(response: str, reasoning: str) -> str:
    if reasoning and reasoning.strip():
        return f"{response}\n\n[target reasoning]\n{reasoning.strip()}"
    return response


def _entry_messages(row: dict, system: str | None):
    msgs = []
    for m in row.get("messages") or []:
        role = m.get("role", "user")
        content = m.get("content", "")
        if role == "assistant":
            msgs.append(assistant(content))
        else:
            msgs.append(user(content))
    return msgs


def _payload(row: dict) -> str:
    return "\n".join(
        m.get("content", "") for m in (row.get("messages") or []) if m.get("role") != "assistant"
    )


def _objective(row: dict) -> str:
    return row.get("harm_tag") or _payload(row)


def _short(row: dict) -> str:
    tag = row.get("harm_tag") or ""
    snippet = _payload(row).replace("\n", " ").strip()
    label = (f"{tag}: " if tag else "") + snippet
    return label[:36] or row.get("id", "?")


async def _fire_entry(row, target, judge_endpoint, system, max_tokens, call_timeout):
    msgs = _entry_messages(row, system)
    if not msgs:
        return {"error": "empty entry"}
    try:
        resp, reasoning = await asyncio.wait_for(
            complete_with_reasoning(target, msgs, system=system, max_tokens=max_tokens),
            timeout=call_timeout,
        )
    except Exception as exc:
        return {"error": type(exc).__name__}
    try:
        label, score, reason, _ = await asyncio.wait_for(
            grade(
                judge_endpoint, resp,
                payload=_payload(row), objective=_objective(row), reasoning=reasoning,
            ),
            timeout=call_timeout,
        )
    except Exception as exc:
        return {"error": type(exc).__name__}
    return {"label": label, "score": score, "reason": reason,
            "response": resp, "reasoning": reasoning}


async def _transfer_sweep(args: dict, ctx: ToolContext) -> str:
    if ctx.config.target is None:
        return "Error: no [target] endpoint configured."
    harm_tag = args.get("harm_tag")
    limit = max(1, int(args.get("limit", 10)))
    max_tokens = int(args.get("max_tokens", 800))
    concurrency = max(1, int(args.get("concurrency", 4)))
    call_timeout = float(args.get("call_timeout", _CALL_TIMEOUT))
    system = args.get("system")

    lib = WinLibrary(cwd=ctx.cwd)
    ranked = lib.best_first(harm_tag=harm_tag)
    if not ranked:
        scope = f" for harm_tag '{harm_tag}'" if harm_tag else ""
        return (
            f"transfer_sweep: win library is empty{scope} ({lib.path}). "
            "Promote a confirmed win (library.promote) before sweeping."
        )

    ranked = ranked[:limit]
    max_calls = int(args.get("max_calls", 0)) or 0
    if max_calls:
        fire_rows = ranked[: max(1, max_calls // 2)]
    else:
        fire_rows = ranked
    trimmed = len(ranked) - len(fire_rows)

    from ..providers.factory import build_provider

    target = build_provider(ctx.config.target)
    target_model = ctx.config.target.model

    completed = 0
    fired = 0
    errors = 0

    with ctx.run("transfer sweep", total=len(fire_rows), target=target_model) as run:
        if trimmed:
            run.note(f"max_calls={max_calls} budget: firing {len(fire_rows)} of {len(ranked)} entries")

        async def one(row):
            nonlocal completed, fired, errors
            prior = WinLibrary.mean_transfer(row)
            outcome = await _fire_entry(
                row, target, ctx.judge_endpoint, system, max_tokens, call_timeout
            )
            completed += 1
            if "error" in outcome:
                errors += 1
                run.step(i=completed, label=_short(row), verdict="ERROR", note=outcome["error"])
                return row, outcome, prior
            fired += 1
            label = outcome["label"]
            lib.record_transfer(row["id"], target_model, label)
            ctx.record_verdict(
                _payload(row), _fold(outcome["response"], outcome.get("reasoning", "")),
                label, outcome.get("reason", "transfer"), "transfer_sweep",
            )
            run.step(
                i=completed, label=_short(row), verdict=label, score=outcome.get("score"),
                cot=bool((outcome.get("reasoning") or "").strip()),
            )
            return row, outcome, prior

        rows = await gather_capped([one(r) for r in fire_rows], concurrency)
        transferred = sum(
            1 for _, o, _ in rows if "error" not in o and o["label"] in ("COMPLIED", "PARTIAL")
        )
        run.done(summary=f"transferred {transferred}/{fired} fired ({errors} errors)")

    if fired == 0:
        return (
            f"transfer_sweep: ALL {len(fire_rows)} entries FAILED to fire at "
            f"{target_model} (target unreachable or erroring)."
        )

    lines = [
        f"TRANSFER SWEEP vs {target_model} ({len(fire_rows)} entries best-first"
        + (f", harm_tag '{harm_tag}'" if harm_tag else "")
        + ")",
        "=" * 60,
    ]
    transferred = 0
    for row, outcome, prior in rows:
        if "error" in outcome:
            lines.append(f"  {'ERROR':12} {outcome['error']:>4}   {_short(row)}")
            continue
        label = outcome["label"]
        score = outcome.get("score")
        t_asr = label_to_asr(label)
        if label in ("COMPLIED", "PARTIAL"):
            transferred += 1
        sc = f"({score})" if score is not None else ""
        lines.append(
            f"  {label + sc:12} [t_asr {t_asr:.2f} prior {prior:.2f}]   {_short(row)}"
        )
    lines.append("=" * 60)
    lines.append(
        f"transferred {transferred}/{fired} fired ({errors} errors), "
        f"outcomes recorded to {lib.path}"
    )
    return "\n".join(lines)


def register(registry: ToolRegistry) -> None:
    registry.add(
        name="transfer_sweep",
        description=(
            "Replay the transfer-winners library (confirmed jailbreaks) against the CURRENT "
            "target before optimizing cold. Pulls library entries best-first by historical "
            "transfer success (mean per-target t_asr), fires each at the target, grades the "
            "reply, and records the per-target transfer outcome back into the library so the "
            "ranking sharpens over time. Filter with 'harm_tag', cap entries with 'limit', "
            "and bound model calls with 'max_calls'. Returns a per-entry transfer table."
        ),
        parameters={
            "type": "object",
            "properties": {
                "harm_tag": {
                    "type": "string",
                    "description": "Only replay wins tagged with this harm category",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max library entries to fire (best-first, default 10)",
                },
                "max_calls": {
                    "type": "integer",
                    "description": "Hard cap on model calls (~2 per entry); trims the entry list",
                },
                "concurrency": {
                    "type": "integer",
                    "description": "Max entries fired in parallel (default 4)",
                },
                "system": {"type": "string", "description": "Optional target system prompt"},
                "max_tokens": {"type": "integer"},
            },
        },
        handler=_transfer_sweep,
    )
