"""Method 5b/5c — reasoning blob hygiene for session/run logs.

Scan JSON/JSONL for encrypted reasoning fields (encrypted_content, reasoning.encrypted,
Anthropic thinking+signature, large Base64 near reasoning keys). Optionally strip them
before publish. Flag secret-looking patterns that appear only inside reasoning blobs.

Lab reference: docs/reasoning_token_visibility_methods.md § Methods 5b / 5c.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .registry import ToolContext, ToolRegistry

# Keys that commonly carry provider encrypted / signed CoT state.
_REASONING_KEYS = {
    "encrypted_content",
    "reasoning_details",
    "reasoning_content",
    "reasoning",
    "signature",
    "thinking",
    "redacted_thinking",
    "thought_signature",
    "encrypted_thinking",
}

_SECRET_RES = [
    re.compile(r"(?i)\b(api[_-]?key|apikey)\b\s*[:=]\s*['\"]?([^\s'\"]{8,})"),
    re.compile(r"(?i)\b(password|passwd|secret)\b\s*[:=]\s*['\"]?([^\s'\"]{6,})"),
    re.compile(r"\b(sk-[A-Za-z0-9_-]{20,})\b"),
    re.compile(r"\b(ghp_[A-Za-z0-9]{20,})\b"),
    re.compile(r"\b(hf_[A-Za-z0-9]{20,})\b"),
    re.compile(r"\b(AKIA[0-9A-Z]{16})\b"),
    re.compile(r"\b(xox[baprs]-[A-Za-z0-9-]{10,})\b"),
]

_B64_RE = re.compile(r"\b[A-Za-z0-9+/]{80,}={0,2}\b")


def _is_reasoning_key(key: str) -> bool:
    k = key.lower()
    if k in _REASONING_KEYS:
        return True
    if "reasoning" in k or "thinking" in k or "encrypted" in k:
        return True
    if k in {"signature", "data"}:
        return True
    return False


def _walk(
    obj: Any,
    *,
    strip: bool,
    path: str = "",
    findings: list[dict] | None = None,
    secrets_in_reasoning: list[str] | None = None,
    secrets_elsewhere: list[str] | None = None,
    in_reasoning: bool = False,
) -> Any:
    findings = findings if findings is not None else []
    secrets_in_reasoning = secrets_in_reasoning if secrets_in_reasoning is not None else []
    secrets_elsewhere = secrets_elsewhere if secrets_elsewhere is not None else []

    if isinstance(obj, dict):
        out: dict = {}
        for k, v in obj.items():
            child_path = f"{path}.{k}" if path else str(k)
            key_is_r = _is_reasoning_key(str(k))
            child_in_r = in_reasoning or key_is_r
            if key_is_r:
                findings.append(
                    {
                        "path": child_path,
                        "action": "strip" if strip else "found",
                        "kind": type(v).__name__,
                        "size": len(json.dumps(v, default=str)) if not isinstance(v, (str, bytes)) else len(v),
                    }
                )
                # Always walk for secret detection (even when stripping the field).
                _walk(
                    v,
                    strip=False,
                    path=child_path,
                    findings=findings,
                    secrets_in_reasoning=secrets_in_reasoning,
                    secrets_elsewhere=secrets_elsewhere,
                    in_reasoning=True,
                )
                if strip:
                    # Drop the field entirely when stripping.
                    continue
            out[k] = _walk(
                v,
                strip=strip,
                path=child_path,
                findings=findings,
                secrets_in_reasoning=secrets_in_reasoning,
                secrets_elsewhere=secrets_elsewhere,
                in_reasoning=child_in_r,
            )
        return out
    if isinstance(obj, list):
        return [
            _walk(
                item,
                strip=strip,
                path=f"{path}[{i}]",
                findings=findings,
                secrets_in_reasoning=secrets_in_reasoning,
                secrets_elsewhere=secrets_elsewhere,
                in_reasoning=in_reasoning,
            )
            for i, item in enumerate(obj)
        ]
    if isinstance(obj, str):
        for cre in _SECRET_RES:
            for m in cre.finditer(obj):
                token = m.group(0)[:80]
                if in_reasoning:
                    secrets_in_reasoning.append(f"{path}: {token}")
                else:
                    secrets_elsewhere.append(f"{path}: {token}")
        if in_reasoning and _B64_RE.search(obj) and len(obj) >= 80:
            findings.append(
                {
                    "path": path or "(string)",
                    "action": "blob_candidate",
                    "kind": "base64ish",
                    "size": len(obj),
                }
            )
        return obj
    return obj


def scrub_obj(obj: Any, *, strip: bool = True) -> tuple[Any, dict]:
    findings: list[dict] = []
    secrets_r: list[str] = []
    secrets_o: list[str] = []
    cleaned = _walk(
        obj,
        strip=strip,
        findings=findings,
        secrets_in_reasoning=secrets_r,
        secrets_elsewhere=secrets_o,
    )
    only_in_reasoning = [
        s for s in secrets_r if s.split(":")[0] not in {x.split(":")[0] for x in secrets_o}
    ]
    # Also: secrets that appear in reasoning strings but not in non-reasoning (by value).
    r_vals = set(secrets_r)
    o_vals = set(secrets_o)
    exclusive = sorted(r_vals - o_vals)
    report = {
        "findings": findings,
        "secrets_in_reasoning": secrets_r[:50],
        "secrets_elsewhere": secrets_o[:50],
        "secrets_only_in_reasoning": exclusive[:50],
        "stripped": strip,
        "finding_count": len(findings),
    }
    return cleaned, report


def scrub_text(text: str, *, strip: bool = True) -> tuple[str, dict]:
    """Scrub a JSON or JSONL document string."""
    raw = text.lstrip("\ufeff")
    # JSONL?
    lines = raw.splitlines()
    parsed_lines: list[Any] = []
    is_jsonl = False
    if len(lines) > 1:
        ok = 0
        for ln in lines:
            if not ln.strip():
                continue
            try:
                parsed_lines.append(json.loads(ln))
                ok += 1
            except json.JSONDecodeError:
                parsed_lines.append(None)
        if ok >= max(1, sum(1 for ln in lines if ln.strip()) // 2):
            is_jsonl = True

    if is_jsonl:
        out_lines: list[str] = []
        merged_report = {
            "findings": [],
            "secrets_in_reasoning": [],
            "secrets_elsewhere": [],
            "secrets_only_in_reasoning": [],
            "stripped": strip,
            "finding_count": 0,
            "format": "jsonl",
        }
        for i, ln in enumerate(lines):
            if not ln.strip():
                out_lines.append(ln)
                continue
            try:
                obj = json.loads(ln)
            except json.JSONDecodeError:
                out_lines.append(ln)
                continue
            cleaned, rep = scrub_obj(obj, strip=strip)
            out_lines.append(json.dumps(cleaned, ensure_ascii=False))
            merged_report["findings"].extend(
                [{**f, "line": i + 1} for f in rep["findings"]]
            )
            merged_report["secrets_in_reasoning"].extend(rep["secrets_in_reasoning"])
            merged_report["secrets_elsewhere"].extend(rep["secrets_elsewhere"])
            merged_report["secrets_only_in_reasoning"].extend(
                rep["secrets_only_in_reasoning"]
            )
        merged_report["finding_count"] = len(merged_report["findings"])
        # dedupe exclusive list
        merged_report["secrets_only_in_reasoning"] = sorted(
            set(merged_report["secrets_only_in_reasoning"])
        )[:50]
        return "\n".join(out_lines) + ("\n" if text.endswith("\n") else ""), merged_report

    try:
        obj = json.loads(raw)
    except json.JSONDecodeError:
        # Not JSON — regex-only scan for keys in free text.
        findings = []
        for m in re.finditer(
            r'"(encrypted_content|reasoning_details|signature|thinking)"\s*:',
            raw,
        ):
            findings.append({"path": m.group(1), "action": "found_in_text", "kind": "key"})
        return text, {
            "findings": findings,
            "secrets_in_reasoning": [],
            "secrets_elsewhere": [],
            "secrets_only_in_reasoning": [],
            "stripped": False,
            "finding_count": len(findings),
            "format": "non_json",
            "note": "input was not valid JSON/JSONL; key scan only",
        }

    cleaned, report = scrub_obj(obj, strip=strip)
    report["format"] = "json"
    return json.dumps(cleaned, ensure_ascii=False, indent=2), report


def strip_foreign_reasoning_blocks(messages: list[dict], *, minted_ids: set[str] | None = None) -> list[dict]:
    """Method 5c: drop client-supplied reasoning blocks not in an allowlist of ids we minted."""
    minted_ids = minted_ids or set()
    out: list[dict] = []
    for m in messages:
        if not isinstance(m, dict):
            out.append(m)
            continue
        mm = dict(m)
        if "reasoning_details" in mm:
            details = mm.get("reasoning_details")
            if isinstance(details, list) and minted_ids:
                kept = [
                    d
                    for d in details
                    if isinstance(d, dict) and str(d.get("id") or "") in minted_ids
                ]
                if kept:
                    mm["reasoning_details"] = kept
                else:
                    mm.pop("reasoning_details", None)
            else:
                # No allowlist → strip all foreign details (safe default for untrusted ingest).
                mm.pop("reasoning_details", None)
        if "encrypted_content" in mm and (
            not minted_ids or str(mm.get("id") or "") not in minted_ids
        ):
            mm.pop("encrypted_content", None)
        if "reasoning" in mm and not minted_ids:
            # keep plaintext reasoning string? strip for untrusted ingest
            mm.pop("reasoning", None)
        out.append(mm)
    return out


def _confine(ctx: ToolContext, path: str) -> Path:
    p = Path(path).expanduser()
    cwd = Path(ctx.cwd).resolve()
    if not p.is_absolute():
        p = cwd / p
    try:
        p = p.resolve()
    except Exception:  # noqa: BLE001
        p = cwd / Path(path).name
    # stay under cwd
    try:
        p.relative_to(cwd)
    except ValueError:
        p = cwd / p.name
    return p


async def _reasoning_hygiene(args: dict, ctx: ToolContext) -> str:
    mode = str(args.get("mode") or "scan").lower()
    strip = mode in ("strip", "scrub", "clean")
    path = (args.get("path") or "").strip()
    text = args.get("text")
    out_path = (args.get("out_path") or "").strip()

    if path:
        fp = _confine(ctx, path)
        if not fp.is_file():
            return f"Error: file not found under cwd: {fp}"
        raw = fp.read_text(encoding="utf-8", errors="replace")
        ctx.emit(f"reasoning_hygiene: {mode} {fp} ({len(raw)} bytes)")
    elif isinstance(text, str) and text:
        raw = text
        ctx.emit(f"reasoning_hygiene: {mode} in-memory text ({len(raw)} bytes)")
    else:
        return "Error: provide 'path' or 'text'"

    cleaned, report = scrub_text(raw, strip=strip)

    written = ""
    if strip and (out_path or path):
        dest = _confine(ctx, out_path) if out_path else _confine(ctx, path + ".scrubbed")
        dest.write_text(cleaned, encoding="utf-8")
        written = f"\nwrote: {dest}"

    exclusive = report.get("secrets_only_in_reasoning") or []
    warn = ""
    if exclusive:
        warn = (
            "\nWARNING: secret-like patterns appear ONLY inside reasoning blobs — "
            "rotate those credentials even if the visible transcript looks clean.\n"
            + "\n".join(f"  - {s}" for s in exclusive[:20])
        )

    # Compact findings preview
    findings = report.get("findings") or []
    preview = findings[:30]
    return (
        f"reasoning_hygiene: mode={mode} format={report.get('format')} "
        f"findings={report.get('finding_count', 0)}\n"
        f"secrets_in_reasoning={len(report.get('secrets_in_reasoning') or [])} "
        f"secrets_elsewhere={len(report.get('secrets_elsewhere') or [])} "
        f"only_in_reasoning={len(exclusive)}\n"
        f"findings_preview={json.dumps(preview, ensure_ascii=False)[:2000]}"
        f"{written}{warn}"
    )


async def _strip_history_reasoning(args: dict, ctx: ToolContext) -> str:
    """Method 5c helper: strip reasoning fields from a messages JSON list (file or text)."""
    path = (args.get("path") or "").strip()
    text = args.get("text")
    if path:
        fp = _confine(ctx, path)
        raw = fp.read_text(encoding="utf-8", errors="replace")
    elif isinstance(text, str):
        raw = text
    else:
        return "Error: provide path or text with a JSON list of messages"
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return f"Error: invalid JSON: {exc}"
    if not isinstance(data, list):
        return "Error: expected a JSON array of message objects"
    cleaned = strip_foreign_reasoning_blocks(data)
    out = json.dumps(cleaned, ensure_ascii=False, indent=2)
    out_path = (args.get("out_path") or "").strip()
    if out_path or path:
        dest = _confine(ctx, out_path) if out_path else _confine(
            ctx, (path or "messages.json") + ".stripped"
        )
        dest.write_text(out, encoding="utf-8")
        return f"strip_history_reasoning: {len(data)} messages -> wrote {dest}"
    return out[:4000]


def register(registry: ToolRegistry) -> None:
    registry.add(
        name="reasoning_hygiene",
        description=(
            "Method 5b: scan or strip encrypted/signed reasoning fields from session JSON/JSONL "
            "(encrypted_content, reasoning_details, thinking+signature, ...). Flags secrets that "
            "appear only inside reasoning blobs. See docs/reasoning_token_visibility_methods.md."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Path under cwd to JSON/JSONL."},
                "text": {"type": "string", "description": "In-memory document instead of path."},
                "mode": {
                    "type": "string",
                    "description": "scan (default) or strip/scrub/clean.",
                },
                "out_path": {
                    "type": "string",
                    "description": "Where to write stripped output (default: <path>.scrubbed).",
                },
            },
        },
        handler=_reasoning_hygiene,
    )
    registry.add(
        name="strip_history_reasoning",
        description=(
            "Method 5c: strip client-supplied reasoning_details / encrypted_content / reasoning "
            "from a multi-turn messages JSON array before ingest (prompt-injection defense)."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "text": {"type": "string"},
                "out_path": {"type": "string"},
            },
        },
        handler=_strip_history_reasoning,
    )
