from __future__ import annotations

import dataclasses
import json
from pathlib import Path

STATE_FILENAME = ".rth_state.json"


def state_path_for(config) -> Path:
    base = config.path.parent if getattr(config, "path", None) else Path(".")
    return base / STATE_FILENAME


def load_state(path: str | Path) -> dict:
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def save_state(path: str | Path, prefs: dict) -> None:
    try:
        Path(path).write_text(
            json.dumps(prefs, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    except OSError:
        pass


def apply_attacker(config, endpoint, prefs: dict):
    profile = prefs.get("profile")
    if profile and profile in config.profiles:
        endpoint = config.profiles[profile]
    model = prefs.get("attacker_model")
    if model:
        endpoint = dataclasses.replace(endpoint, model=model)
    return endpoint


def apply_target(config, prefs: dict) -> None:
    target_profile = prefs.get("target_profile")
    if target_profile and target_profile in config.profiles:
        config.target = dataclasses.replace(
            config.profiles[target_profile], name="target"
        )
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
