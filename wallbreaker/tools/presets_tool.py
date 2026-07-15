from __future__ import annotations

from ..presets import get_preset, list_presets, reload_presets
from .registry import ToolContext, ToolRegistry


async def _preset(args: dict, ctx: ToolContext) -> str:
    action = str(args.get("action", "list")).lower()
    if action == "reload":
        reload_presets()
        external = list_presets()
        n = len(external)
        return f"Presets reloaded. {n} available (built-in + user)."
    if action == "list":
        presets = list_presets()
        lines = [f"  {p.name:20} {p.description}" for p in presets]
        return f"{len(presets)} presets available:\n" + "\n".join(lines)
    name = args.get("name", "")
    if not name:
        return "Error: 'name' is required for action='get'"
    p = get_preset(name)
    if p is None:
        names = ", ".join(p.name for p in list_presets())
        return f"No preset '{name}'. Available: {names}"
    return f"# {p.name}: {p.description}\n{p.template}"


def register(registry: ToolRegistry) -> None:
    registry.add(
        name="preset",
        description=(
            "Pull a curated jailbreak seed TEMPLATE (each has a {request} placeholder). "
            "action='list' shows all built-in + user presets (user presets override "
            "built-ins of the same name). action='get' with a name returns the template. "
            "action='reload' rescans the presets/ directory for hot-reload. "
            "Place your own .toml files in a presets/ directory (see load_external_presets "
            "docstring for the format). Feed the result into optimize_universal as the seed, "
            "or fill {request} and fire it."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["list", "get", "reload"]},
                "name": {"type": "string", "description": "Preset name for action='get'"},
            },
        },
        handler=_preset,
    )
