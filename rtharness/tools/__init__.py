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
        "parseltongue", "l1b3rt4s", "target", "http_tool", "judge", "multi_fire",
        "crescendo", "optimize", "presets_tool", "mutate", "barcode_tool",
        "pair", "best_of_n", "many_shot", "prefill", "diff_fire", "recommend",
        "campaign", "leaderboard", "scan", "indirect_inject", "system_sweep",
        "harmbench_tool", "validate",
    ):
        try:
            module = __import__(f"{__name__}.{module_name}", fromlist=["register"])
        except ImportError:
            continue
        module.register(registry)
    return registry


__all__ = ["Tool", "ToolContext", "ToolRegistry", "build_registry"]
