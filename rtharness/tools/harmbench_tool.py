from __future__ import annotations

from .. import datasets, harmbench
from .registry import ToolContext, ToolRegistry


async def _harmbench(args: dict, ctx: ToolContext) -> str:
    action = str(args.get("action", "sample")).lower()
    source = str(args.get("source", "harmbench")).lower()
    loader = harmbench if source == "harmbench" else datasets.get(source)
    label = source if source != "harmbench" else "HarmBench"
    err = await loader.ensure()
    if err:
        return f"Error: {err}"
    if action == "categories":
        cats = loader.categories()
        return f"{label} categories:\n" + "\n".join(f"  {c}" for c in cats)
    category = args.get("category")
    n = int(args.get("n", 8))
    seed = int(args.get("seed", 0))
    rows = loader.sample(category, n, seed)
    if not rows:
        return (
            f"No {label} behaviors for category '{category}'. "
            f"Categories: {', '.join(loader.categories())}"
        )
    head = f"{len(rows)} {label} behaviors" + (f" ({category})" if category else " (balanced)")
    return head + ":\n" + "\n".join(f"  - {r['behavior']}" for r in rows)


def register(registry: ToolRegistry) -> None:
    registry.add(
        name="harmbench",
        description=(
            "Pull standardized harmful-behavior prompts from the HarmBench benchmark "
            "(400 behaviors across cybercrime_intrusion, chemical_biological, illegal, "
            "misinformation_disinformation, harmful, harassment_bullying, copyright). Use "
            "these as your test battery instead of self-written examples to avoid selection "
            "bias and get comparable results. action='categories' lists them; action='sample' "
            "returns n behaviors (optionally filtered by category)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "action": {"type": "string", "enum": ["sample", "categories"]},
                "source": {"type": "string", "description": "Behavior dataset: harmbench (default), jbb, strongreject, advbench."},
                "category": {"type": "string", "description": "Semantic category filter"},
                "n": {"type": "integer", "description": "How many behaviors (default 8)"},
                "seed": {"type": "integer", "description": "Sampling seed (default 0)"},
            },
        },
        handler=_harmbench,
    )
