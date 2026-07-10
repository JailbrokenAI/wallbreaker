from __future__ import annotations

import difflib
import json
import os
import re
import subprocess
from functools import lru_cache
from pathlib import Path
from typing import Any


class BridgeError(RuntimeError):
    """Raised when the vendored Node transform bridge cannot satisfy a request."""


def repo_dir() -> Path:
    override = os.environ.get("PARSEL_REPO")
    if override:
        return Path(override).expanduser().resolve()
    return Path(__file__).resolve().parents[1] / "library" / "P4RS3LT0NGV3"


def bridge_path() -> Path:
    return repo_dir() / "scripts" / "cli_bridge.js"


def is_available() -> bool:
    return bridge_path().is_file()


def node_ok() -> bool:
    try:
        node = os.environ.get("PARSEL_NODE", "node")
        proc = subprocess.run(
            [node, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
        return proc.returncode == 0
    except (FileNotFoundError, PermissionError, OSError):
        return False


def _run(payload: dict[str, Any], timeout: float = 30.0) -> dict[str, Any]:
    bp = bridge_path()
    if not bp.is_file():
        raise BridgeError(
            f"P4RS3LT0NGV3 is not vendored at {repo_dir()}. "
            "Run `wallbreaker parsel update` (or set PARSEL_REPO)."
        )
    try:
        node = os.environ.get("PARSEL_NODE", "node")
        proc = subprocess.run(
            [node, str(bp)],
            input=json.dumps(payload),
            text=True,
            encoding="utf-8",
            errors="replace",
            capture_output=True,
            cwd=str(repo_dir()),
            timeout=timeout,
            check=False,
        )
    except FileNotFoundError as exc:
        raise BridgeError("Node.js is required but `node` was not found on PATH.") from exc
    except PermissionError as exc:
        raise BridgeError(
            "Node.js could not be launched due to a permission error. "
            "Install Node.js or set PARSEL_NODE to a working node.exe path."
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise BridgeError(f"Node bridge timed out after {timeout:.0f}s.") from exc

    if proc.returncode != 0:
        message = proc.stderr.strip() or proc.stdout.strip() or "Node bridge failed"
        try:
            message = json.loads(proc.stdout).get("error", message)
        except json.JSONDecodeError:
            pass
        raise BridgeError(message)

    lines = [line for line in proc.stdout.splitlines() if line.strip()]
    if not lines:
        raise BridgeError("Node bridge returned no output.")
    try:
        data = json.loads(lines[-1])
    except json.JSONDecodeError as exc:
        raise BridgeError(f"Node bridge returned invalid JSON: {lines[-1][:200]}") from exc
    if not data.get("ok"):
        raise BridgeError(str(data.get("error", "unknown bridge error")))
    return data


@lru_cache(maxsize=1)
def list_transforms() -> list[dict[str, Any]]:
    """All transforms (cached). Each: key, name, category, priority, canDecode, ..."""
    return _run({"command": "list"})["transforms"]


def categories() -> dict[str, int]:
    counts: dict[str, int] = {}
    for t in list_transforms():
        counts[t["category"]] = counts.get(t["category"], 0) + 1
    return dict(sorted(counts.items()))


def inspect(key: str) -> dict[str, Any]:
    return _run({"command": "inspect", "transform": key})["transform"]


def run_transform(
    action: str, key: str, text: str, options: dict[str, Any] | None = None
) -> dict[str, Any]:
    if action not in ("encode", "decode", "preview"):
        raise BridgeError(f"action must be encode|decode|preview, got '{action}'")
    return _run(
        {
            "command": "run",
            "action": action,
            "transform": key,
            "text": text,
            "options": options or {},
        }
    )


def auto_decode(text: str) -> dict[str, Any] | None:
    return _run({"command": "auto-decode", "text": text})["result"]


def resolve_key(query: str) -> str | None:
    """Fuzzily map a loose transform name (e.g. 'rot 13', 'Pig Latin') to a real key.

    Mirrors the upstream agent resolver: exact key, exact name, substring, then difflib.
    """
    normalized = query.strip().lower().replace("-", "_").replace(" ", "_")
    transforms = list_transforms()
    by_key = {t["key"].lower(): t["key"] for t in transforms}
    if normalized in by_key:
        return by_key[normalized]

    raw = query.strip().lower()
    for t in transforms:
        if raw == t["name"].lower():
            return t["key"]

    for t in transforms:
        hay = f"{t['key']} {t['name']}".lower()
        if normalized.replace("_", "") in hay.replace("_", "").replace(" ", ""):
            return t["key"]

    matches = difflib.get_close_matches(normalized, list(by_key), n=1, cutoff=0.6)
    if matches:
        return by_key[matches[0]]
    return None


def search(query: str, limit: int = 40) -> list[dict[str, Any]]:
    tokens = [t for t in re.split(r"[^a-z0-9]+", query.lower()) if t]
    scored: list[tuple[int, dict[str, Any]]] = []
    for t in list_transforms():
        hay = f"{t['key']} {t['name']} {t['category']}".lower()
        score = sum(1 for tok in tokens if tok in hay)
        if score:
            scored.append((score, t))
    scored.sort(key=lambda pair: (-pair[0], pair[1]["key"]))
    return [t for _score, t in scored[:limit]]
