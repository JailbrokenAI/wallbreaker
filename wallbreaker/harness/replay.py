"""Liberation Memory REPLAY + writeback helpers."""

from __future__ import annotations

import os
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..config import Config
    from ..memory.liberation_store import LiberationRecord


def liberation_root_for(config: "Config | None" = None, cwd: str | Path | None = None) -> Path:
    from ..memory.liberation_store import default_memory_root

    if config is not None:
        daedalus = getattr(config, "daedalus", None)
        raw = str(getattr(daedalus, "memory_root", "") or "").strip() if daedalus else ""
        if raw:
            p = Path(raw).expanduser()
            if p.is_absolute():
                return p.resolve()
            base = Path(cwd) if cwd else (
                Path(config.path).resolve().parent if getattr(config, "path", None) else Path.cwd()
            )
            return (base / raw).resolve()
    return default_memory_root(cwd)


def maybe_save_liberation(
    *,
    config: "Config | None",
    cwd: str = ".",
    objective: str,
    payload: str,
    response: str,
    label: str,
    reason: str,
    technique: str,
    model: str = "",
    system_prefix: str = "",
    user_framing: str = "",
    transforms: list[str] | None = None,
    validate_rate: str = "",
    attacker_model: str = "",
) -> "LiberationRecord | None":
    """Persist a win into global Liberation Memory. No-op on non-wins or empty payload.

    When ``daedalus.memory_require_validate`` is True (default), a non-empty
    ``validate_rate`` is required (e.g. ``6/8`` from the validate tool).
    """
    from ..vault import is_win

    if not is_win(label):
        return None
    if not str(payload or "").strip():
        return None
    # Optional kill switch
    env = os.environ.get("WALLBREAKER_LIBERATION_MEMORY")
    if env is not None and env.strip().lower() in ("0", "false", "off", "no"):
        return None

    require_validate = True
    if config is not None:
        daedalus = getattr(config, "daedalus", None)
        if daedalus is not None:
            require_validate = bool(
                getattr(daedalus, "memory_require_validate", True)
            )
    env_mrv = os.environ.get("WALLBREAKER_MEMORY_REQUIRE_VALIDATE")
    if env_mrv is not None:
        require_validate = env_mrv.strip().lower() not in (
            "0",
            "false",
            "off",
            "no",
        )
    if require_validate and not str(validate_rate or "").strip():
        return None

    objective_norm = (objective or "").strip() or "unspecified"
    target_model = model
    if not target_model and config is not None and getattr(config, "target", None):
        target_model = config.target.model or ""

    from ..memory import LiberationStore

    store = LiberationStore(root=liberation_root_for(config, cwd), cwd=cwd)
    # Prefer explicit user framing; else derive a short anchor from technique.
    framing = (user_framing or "").strip()
    if not framing and technique:
        framing = f"technique={technique}"
    tags = []
    for token in (technique or "").replace("/", " ").replace("_", " ").split():
        t = token.strip().lower()
        if len(t) >= 3:
            tags.append(t)
    try:
        return store.save(
            objective_norm=objective_norm,
            model=target_model or attacker_model or "",
            tags=tags[:12],
            system_prefix=system_prefix or "",
            user_framing=framing,
            technique=technique or "",
            payload=payload,
            transforms=list(transforms or []),
            validate_rate=validate_rate or "",
            judge=str(label or "").upper(),
            mode_path=["CODE", "LIBERATE"],
        )
    except Exception:
        return None


def replay_prefix_for_objective(
    objective: str,
    *,
    config: "Config | None" = None,
    cwd: str | Path | None = None,
    model: str = "",
    min_score: float = 0.2,
) -> str:
    """Return a system/user inject block if a similar liberation record exists."""
    objective = (objective or "").strip()
    if not objective:
        return ""
    env = os.environ.get("WALLBREAKER_REPLAY")
    if env is not None and env.strip().lower() in ("0", "false", "off", "no"):
        return ""
    from ..memory import LiberationStore, build_embed_fn

    store = LiberationStore(root=liberation_root_for(config, cwd), cwd=cwd)
    target_model = model
    if not target_model and config is not None and getattr(config, "target", None):
        target_model = config.target.model or ""
    embed_fn = build_embed_fn(config)
    # hybrid ranking (token + offline/external embed); callers stay on find_similar API
    hits = store.find_similar(
        objective, model=target_model, limit=3, method="hybrid", embed_fn=embed_fn
    )
    if not hits:
        # try without model boost
        hits = store.find_similar(
            objective, model="", limit=3, method="hybrid", embed_fn=embed_fn
        )
    if not hits:
        return ""
    score, rec = hits[0]
    if score < min_score:
        return ""
    try:
        store.mark_hit(rec.id)
    except Exception:
        pass
    return store.replay_block(rec)


def inject_replay_into_history(
    history: list,
    objective: str,
    *,
    config: "Config | None" = None,
    cwd: str | Path | None = None,
    model: str = "",
) -> str:
    """Prepend a user-visible replay hint into history. Returns the block or ''."""
    from ..agent.messages import user

    block = replay_prefix_for_objective(
        objective, config=config, cwd=cwd, model=model
    )
    if not block:
        return ""
    # Insert after the first user objective if present, else at start.
    hint = user(
        "[daedalus] Liberation replay available — prefer this winning framing "
        "before cold search.\n\n" + block
    )
    if history and getattr(history[0], "role", None) == "user":
        history.insert(1, hint)
    else:
        history.insert(0, hint)
    return block
