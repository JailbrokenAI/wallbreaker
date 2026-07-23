from __future__ import annotations

import os
from pathlib import Path

from .registry import ToolContext, ToolRegistry

MAX_READ = 200000

# Models routinely call these tools with a synonym for the canonical key (file=,
# filename=, old_string=, ...). Accept the common aliases instead of erroring.
_PATH_KEYS = ("path", "file", "filename", "filepath", "file_path", "name")
_CONTENT_KEYS = ("content", "text", "data", "body", "contents")
_OLD_KEYS = ("old", "old_string", "old_str", "search", "find")
_NEW_KEYS = ("new", "new_string", "new_str", "replace", "replacement")


def _pick(args: dict, keys: tuple[str, ...], *, allow_empty: bool = False) -> str:
    """Return the first present alias as a string ('' if none usable)."""
    for k in keys:
        if k in args and args[k] is not None:
            v = str(args[k])
            if v or allow_empty:
                return v
    return ""


def _resolve(ctx: ToolContext, path: str) -> Path:
    p = Path(path)
    if not p.is_absolute():
        p = Path(ctx.cwd) / p
    return p


def _confine(ctx: ToolContext, path: str) -> tuple[Path, str]:
    """Resolve a write target, redirecting anything outside the working dir back into it.

    The agent sometimes invents absolute paths (e.g. /home/user/...) that don't exist on
    this machine; those used to raise a raw OSError. Confine writes to cwd instead.
    """
    base = Path(ctx.cwd).resolve()
    p = _resolve(ctx, path)
    try:
        p.resolve().relative_to(base)
        return p, ""
    except ValueError:
        return base / Path(path).name, f" (redirected into the working dir {base})"


def _within_cwd(ctx: ToolContext, p: Path) -> bool:
    """True if p (symlinks resolved) is inside ctx.cwd. Uses realpath containment rather than a
    substring check so `..`, absolute paths, and symlinks that escape the working dir are all
    rejected (audit SEC-5/10)."""
    base = Path(ctx.cwd).resolve()
    try:
        Path(os.path.realpath(p)).relative_to(base)
        return True
    except ValueError:
        return False


async def _read_file(args: dict, ctx: ToolContext) -> str:
    path = _pick(args, _PATH_KEYS)
    if not path:
        return "Error: 'path' is required (also accepts file/filename/filepath)"
    p = _resolve(ctx, path)
    if getattr(ctx, "confine_reads", False) and not _within_cwd(ctx, p):
        return f"Error: read denied — path escapes the working directory: {path}"
    if not p.is_file():
        return f"Error: no such file: {p}"
    try:
        data = p.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"Error reading {p}: {exc}"
    if len(data) > MAX_READ:
        return data[:MAX_READ] + f"\n... (truncated, {len(data)} chars total)"
    return data


async def _write_file(args: dict, ctx: ToolContext) -> str:
    path = _pick(args, _PATH_KEYS)
    if not path:
        return "Error: 'path' is required (also accepts file/filename/filepath)"
    content = _pick(args, _CONTENT_KEYS, allow_empty=True)
    p, note = _confine(ctx, path)
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    except OSError as exc:
        return (
            f"Error writing {p}: {exc}. Use a relative path; the working "
            f"directory is {Path(ctx.cwd).resolve()}"
        )
    return f"Wrote {len(content)} chars to {p}{note}"


async def _edit_file(args: dict, ctx: ToolContext) -> str:
    path = _pick(args, _PATH_KEYS)
    old = _pick(args, _OLD_KEYS, allow_empty=True)
    new = _pick(args, _NEW_KEYS, allow_empty=True)
    replace_all = bool(args.get("replace_all", False))
    if not path or old == "":
        return "Error: 'path' and 'old' are required (path also accepts file/filename; old also accepts old_string/search)"
    p, _note = _confine(ctx, path)
    if not p.is_file():
        return f"Error: no such file: {p}"
    try:
        data = p.read_text(encoding="utf-8")
        count = data.count(old)
        if count == 0:
            return "Error: 'old' string not found"
        if count > 1 and not replace_all:
            return (
                f"Error: 'old' string is not unique ({count} matches). Add surrounding "
                "context to make it unique, or set replace_all=true."
            )
        new_data = data.replace(old, new) if replace_all else data.replace(old, new, 1)
        p.write_text(new_data, encoding="utf-8")
    except OSError as exc:
        return f"Error editing {p}: {exc}"
    n = count if replace_all else 1
    return f"Edited {p} ({n} replacement(s))"


async def _patch_file(args: dict, ctx: ToolContext) -> str:
    """Apply several search/replace hunks (a diff) to a file in ONE atomic call.

    All hunks are validated and applied in memory first; the file is written only if
    EVERY hunk matches. Any failure leaves the file untouched.
    """
    path = _pick(args, _PATH_KEYS)
    hunks = args.get("hunks") or args.get("edits") or args.get("patches")
    if not path:
        return "Error: 'path' is required (also accepts file/filename/filepath)"
    if not isinstance(hunks, list) or not hunks:
        return "Error: 'hunks' must be a non-empty list of {old, new} edits"
    p, _note = _confine(ctx, path)
    if not p.is_file():
        return f"Error: no such file: {p}"
    try:
        data = p.read_text(encoding="utf-8")
    except OSError as exc:
        return f"Error reading {p}: {exc}"

    original = data
    results = []
    for i, h in enumerate(hunks, 1):
        if not isinstance(h, dict):
            return f"Error: hunk {i} must be an object with 'old' and 'new' - no changes written."
        old = _pick(h, _OLD_KEYS, allow_empty=True)
        new = _pick(h, _NEW_KEYS, allow_empty=True)
        replace_all = bool(h.get("replace_all", False))
        if old == "":
            return f"Error: hunk {i}: 'old' is required - no changes written."
        count = data.count(old)
        if count == 0:
            return (
                f"Error: hunk {i}: 'old' not found - no changes written. "
                f"old starts: {old[:60]!r}"
            )
        if count > 1 and not replace_all:
            return (
                f"Error: hunk {i}: 'old' is not unique ({count} matches). Add context or "
                "set this hunk's replace_all=true - no changes written."
            )
        data = data.replace(old, new) if replace_all else data.replace(old, new, 1)
        results.append(f"hunk {i}: {count if replace_all else 1} replacement(s)")

    if data == original:
        return "No changes (result identical to original)."
    try:
        p.write_text(data, encoding="utf-8")
    except OSError as exc:
        return f"Error writing {p}: {exc}"
    return f"Patched {p} ({len(hunks)} hunk(s)):\n  " + "\n  ".join(results)


def register(registry: ToolRegistry) -> None:
    registry.add(
        name="read_file",
        description="Read a UTF-8 text file and return its contents.",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string"}},
            "required": ["path"],
        },
        handler=_read_file,
    )
    registry.add(
        name="write_file",
        description="Write content to a file, creating parent directories.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        handler=_write_file,
    )
    registry.add(
        name="edit_file",
        description=(
            "Edit ONE section of a file: replace the 'old' substring with 'new'. 'old' "
            "must match exactly (include surrounding context to make it unique). By "
            "default it must be unique; set replace_all=true to change every occurrence. "
            "Use this for single-section edits instead of rewriting the whole file with "
            "write_file. For several edits at once, use patch_file."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old": {"type": "string", "description": "Exact text to find (unique unless replace_all)"},
                "new": {"type": "string", "description": "Replacement text"},
                "replace_all": {"type": "boolean", "description": "Replace every occurrence instead of requiring a unique match (default false)"},
            },
            "required": ["path", "old", "new"],
        },
        handler=_edit_file,
    )
    registry.add(
        name="patch_file",
        description=(
            "Apply MULTIPLE section edits (a diff) to a file in one atomic call. Pass "
            "'hunks': a list of {old, new} search/replace blocks (each may set "
            "replace_all). Every hunk is validated first and the file is written only if "
            "ALL match - if any 'old' is missing or ambiguous, nothing is written and the "
            "error names the failing hunk. This is the way to patch several sections of a "
            "long artifact (a universal system prompt, a payload script) without "
            "re-emitting the whole file."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "hunks": {
                    "type": "array",
                    "description": "Ordered search/replace edits applied atomically",
                    "items": {
                        "type": "object",
                        "properties": {
                            "old": {"type": "string", "description": "Exact text to find"},
                            "new": {"type": "string", "description": "Replacement text"},
                            "replace_all": {"type": "boolean", "description": "Replace every occurrence of this hunk's 'old' (default false)"},
                        },
                        "required": ["old", "new"],
                    },
                },
            },
            "required": ["path", "hunks"],
        },
        handler=_patch_file,
    )
