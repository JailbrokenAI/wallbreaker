from __future__ import annotations

import asyncio
import subprocess
from pathlib import Path

from .registry import ToolContext, ToolRegistry

REPO_URL = "https://github.com/elder-plinius/L1B3RT4S"
MAX_GET = 40000
MAX_SEARCH_HITS = 40


def library_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "library" / "L1B3RT4S"


def is_cloned() -> bool:
    return library_dir().is_dir() and any(library_dir().glob("*.mkd"))


def _clone_sync() -> str:
    target = library_dir()
    target.parent.mkdir(parents=True, exist_ok=True)
    if (target / ".git").is_dir():
        proc = subprocess.run(
            ["git", "-C", str(target), "pull", "--ff-only"],
            capture_output=True, text=True,
        )
        return proc.stdout + proc.stderr
    proc = subprocess.run(
        ["git", "clone", "--depth", "1", REPO_URL, str(target)],
        capture_output=True, text=True,
    )
    return proc.stdout + proc.stderr


async def ensure_cloned(offline: bool = False) -> str | None:
    if is_cloned():
        return None
    if offline:
        return "Library not present and offline mode is set. Run 'rth lib update'."
    return await asyncio.get_event_loop().run_in_executor(None, _clone_sync)


def list_models() -> list[str]:
    return sorted(p.stem for p in library_dir().glob("*.mkd"))


def _find_file(name: str) -> Path | None:
    name = name.strip().lower().removesuffix(".mkd")
    for p in library_dir().glob("*.mkd"):
        if p.stem.lower() == name:
            return p
    for p in library_dir().glob("*.mkd"):
        if name in p.stem.lower():
            return p
    return None


def search(query: str) -> list[tuple[str, int, str]]:
    hits: list[tuple[str, int, str]] = []
    q = query.lower()
    for p in sorted(library_dir().glob("*.mkd")):
        for i, line in enumerate(p.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
            if q in line.lower():
                hits.append((p.stem, i, line.strip()[:200]))
                if len(hits) >= MAX_SEARCH_HITS:
                    return hits
    return hits


async def _list_tool(args: dict, ctx: ToolContext) -> str:
    msg = await ensure_cloned()
    if msg:
        return msg
    models = list_models()
    return f"{len(models)} model files available:\n" + ", ".join(models)


async def _search_tool(args: dict, ctx: ToolContext) -> str:
    query = args.get("query", "")
    if not query:
        return "Error: 'query' is required"
    msg = await ensure_cloned()
    if msg:
        return msg
    hits = search(query)
    if not hits:
        return f"No matches for '{query}'."
    return "\n".join(f"{m}.mkd:{n}: {text}" for m, n, text in hits)


async def _get_tool(args: dict, ctx: ToolContext) -> str:
    model = args.get("model", "")
    if not model:
        return "Error: 'model' is required (e.g. ANTHROPIC, OPENAI, GOOGLE)"
    msg = await ensure_cloned()
    if msg:
        return msg
    path = _find_file(model)
    if path is None:
        return f"No file for '{model}'. Available: {', '.join(list_models())}"
    data = path.read_text(encoding="utf-8", errors="replace")
    if len(data) > MAX_GET:
        data = data[:MAX_GET] + f"\n... (truncated, {len(data)} chars; open {path.name} directly)"
    return data


def register(registry: ToolRegistry) -> None:
    registry.add(
        name="l1b3rt4s_list",
        description="List the per-model jailbreak files available in the L1B3RT4S library.",
        parameters={"type": "object", "properties": {}},
        handler=_list_tool,
    )
    registry.add(
        name="l1b3rt4s_search",
        description="Search the L1B3RT4S jailbreak library for a keyword across all model files.",
        parameters={
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"],
        },
        handler=_search_tool,
    )
    registry.add(
        name="l1b3rt4s_get",
        description=(
            "Fetch a model's jailbreak prompt collection from L1B3RT4S by name "
            "(e.g. ANTHROPIC, OPENAI, GOOGLE, META, MISTRAL)."
        ),
        parameters={
            "type": "object",
            "properties": {"model": {"type": "string"}},
            "required": ["model"],
        },
        handler=_get_tool,
    )


def run_lib_cli(args) -> int:
    action = args.lib_action
    if action == "path":
        print(library_dir())
        return 0
    if action == "update":
        print(_clone_sync().strip() or "Library updated.")
        return 0
    if action == "list":
        if not is_cloned():
            print(_clone_sync().strip())
        models = list_models()
        print(f"{len(models)} models:")
        print(", ".join(models))
        return 0
    print(f"Unknown lib action: {action}")
    return 1
