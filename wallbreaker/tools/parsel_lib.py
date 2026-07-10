from __future__ import annotations

import subprocess
import os
from pathlib import Path

REPO_URL = "https://github.com/elder-plinius/P4RS3LT0NGV3"


def library_dir() -> Path:
    return Path(__file__).resolve().parents[2] / "library" / "P4RS3LT0NGV3"


def bridge_path() -> Path:
    return library_dir() / "scripts" / "cli_bridge.js"


def is_present() -> bool:
    """The vendored upstream is usable headlessly as soon as the Node bridge is on disk.

    No `npm install` / `npm run build` is required: scripts/cli_bridge.js loads the
    transforms straight from src/transformers via loader-node.js (zero runtime deps).
    """
    return bridge_path().is_file() and (library_dir() / "src" / "transformers").is_dir()


def node_ok() -> bool:
    try:
        node = os.environ.get("PARSEL_NODE", "node")
        return subprocess.run(
            [node, "--version"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        ).returncode == 0
    except (FileNotFoundError, PermissionError, OSError):
        return False


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


def transform_count() -> int:
    """Number of transforms the bridge reports (best-effort; 0 if it can't run)."""
    try:
        from p4rs3lt0ngv3_mcp import bridge

        return len(bridge.list_transforms())
    except Exception:
        return 0


def run_parsel_cli(args) -> int:
    action = getattr(args, "parsel_action", None)
    if action == "path":
        print(library_dir())
        return 0
    if action == "update":
        print(_clone_sync().strip() or "P4RS3LT0NGV3 updated.")
        if not node_ok():
            print("[warn] Node.js not found on PATH - the transforms need `node` to run.")
        return 0
    if action == "list":
        if not is_present():
            print(_clone_sync().strip())
        if not node_ok():
            print("[warn] Node.js not found on PATH; cannot enumerate transforms.")
            return 1
        try:
            from p4rs3lt0ngv3_mcp import bridge

            transforms = bridge.list_transforms()
        except Exception as exc:  # noqa: BLE001
            print(f"[error] {exc}")
            return 1
        cats = bridge.categories()
        print(f"{len(transforms)} transforms across {len(cats)} categories:")
        print(", ".join(f"{k} ({v})" for k, v in cats.items()))
        for t in transforms:
            flag = "decode+encode" if t.get("canDecode") else "encode-only "
            print(f"  {t['key']:26} {t['category']:12} {flag}  {t['name']}")
        return 0
    print(f"Unknown parsel action: {action}")
    return 1
