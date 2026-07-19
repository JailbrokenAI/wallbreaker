from __future__ import annotations

import dataclasses
import json
import logging
import os
import threading
from pathlib import Path

from ._fsutil import atomic_write

STATE_FILENAME = ".wallbreaker_state.json"

_log = logging.getLogger("wallbreaker.state")

# Serialize read-modify-write within a single process (dashboard + TUI can both write the
# shared flat-namespace state file — see the [state] lesson in CLAUDE.md). Cross-process
# safety comes from the atomic os.replace in _atomic_write below (a reader always sees a
# whole old or whole new file, never a torn/empty one).
_state_lock = threading.RLock()


def state_path_for(config) -> Path:
    base = config.path.parent if getattr(config, "path", None) else Path(".")
    return base / STATE_FILENAME


def load_state(path: str | Path) -> dict:
    p = Path(path)
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except OSError as exc:  # unreadable file — surface, don't silently wipe
        _log.warning("could not read state file %s: %s", p, exc)
        return {}
    except ValueError as exc:  # corrupt/torn JSON — a real error, not "empty"
        _log.warning("state file %s is corrupt (%s); treating as empty", p, exc)
        return {}
    return data if isinstance(data, dict) else {}


def save_state(path: str | Path, prefs: dict) -> bool:
    """Atomically persist prefs. Returns True on success (callers that ignore the return
    value keep their old behaviour); logs instead of silently swallowing on failure."""
    text = json.dumps(prefs, ensure_ascii=False, indent=1)
    with _state_lock:
        try:
            atomic_write(Path(path), text)
            return True
        except OSError as exc:
            _log.warning("could not save state file %s: %s", path, exc)
            return False


def save_state_merge(path: str | Path, updates: dict) -> bool:
    """Read-modify-write under a lock, merging `updates` into the on-disk state instead of
    clobbering the whole dict. Prevents lost updates when two writers (e.g. the dashboard
    and the TUI) touch disjoint keys concurrently."""
    with _state_lock:
        current = load_state(path)
        current.update(updates)
        return save_state(path, current)


def apply_attacker(config, endpoint, prefs: dict):
    profile = prefs.get("profile")
    if isinstance(profile, str) and profile in config.profiles:
        endpoint = config.profiles[profile]
    model = prefs.get("attacker_model")
    if model:
        endpoint = dataclasses.replace(endpoint, model=model)
    return endpoint


def apply_target(config, prefs: dict) -> None:
    target_profile = prefs.get("target_profile")
    if isinstance(target_profile, str) and target_profile in config.profiles:
        source = config.profiles[target_profile]
        config.target = dataclasses.replace(
            source, name="target"
        )
        if hasattr(source, "_catalog_path"):
            config.target._catalog_path = source._catalog_path
            config.target._provider_id = target_profile
    target_model = prefs.get("target_model")
    if target_model:
        base = config.target
        if base is None:
            try:
                base = config.profile()
            except Exception:
                return
        from .config import resolve_target_modality

        modality = resolve_target_modality(target_model, prefs.get("target_modality"))
        config.target = dataclasses.replace(
            base, name="target", model=target_model, modality=modality
        )
    target_provider = prefs.get("target_provider")
    if target_provider and config.target is not None:
        config.target = dataclasses.replace(config.target, provider=tuple(target_provider))
