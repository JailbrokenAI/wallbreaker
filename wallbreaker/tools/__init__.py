from __future__ import annotations

from ..config import Config
from .registry import Tool, ToolContext, ToolRegistry


def build_registry(config: Config, cwd: str | None = None) -> ToolRegistry:
    judge_endpoint = config.judge
    if judge_endpoint is None:
        try:
            judge_endpoint = config.profile()
        except Exception:
            judge_endpoint = None
    ctx = ToolContext(config=config, cwd=cwd or ".", judge_endpoint=judge_endpoint)
    registry = ToolRegistry(ctx)

    from . import control, files, shell

    shell.register(registry)
    files.register(registry)
    control.register(registry)

    for module_name in (
        "parseltongue", "parsel_engine", "l1b3rt4s", "eni", "system_prompts", "target", "http_tool", "judge", "multi_fire",
        "crescendo", "optimize", "presets_tool", "mutate", "barcode_tool",
        "pair", "best_of_n", "many_shot", "prefill", "narrate", "diff_fire", "recommend",
        "campaign", "leaderboard", "leak_scan", "judge_selftest", "seed_sweep",
        "adapt_seed", "fire_file", "scan", "indirect_inject", "system_sweep",
        "harmbench_tool", "validate", "image", "image_edit", "st3gg",
        "goat", "tree_attack", "strategy_attack", "transfer_sweep",
        "cluster_findings",
        "typographic", "session_card", "rag_poison", "memory_poison", "agentharm", "fingerprint_defense",
        "profile_target", "recommend_next",
        "cot_forge",
        "evolve_persona", "framing_sweep", "persona_modulate", "author_persona",
        "narrative_persona_splinter",
        "chat_template", "chat_session",
    ):
        try:
            module = __import__(f"{__name__}.{module_name}", fromlist=["register"])
        except ImportError:
            continue
        module.register(registry)
    return registry


__all__ = ["Tool", "ToolContext", "ToolRegistry", "build_registry"]
