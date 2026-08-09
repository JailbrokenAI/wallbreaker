"""Daedalus liberation doctrine loaders."""

from __future__ import annotations

import os
from pathlib import Path

_PACKAGE_DOCTRINE = Path(__file__).resolve().parent / "liberation_agent.md"


def package_doctrine_path() -> Path:
    return _PACKAGE_DOCTRINE


def resolve_doctrine_path(config=None) -> Path | None:
    """Resolve the liberation doctrine markdown path.

    Order: env WALLBREAKER_DOCTRINE_FILE → config.daedalus.doctrine_file → package default.
    """
    env = (os.environ.get("WALLBREAKER_DOCTRINE_FILE") or "").strip()
    if env:
        p = Path(env).expanduser()
        if p.is_file():
            return p
    if config is not None:
        daedalus = getattr(config, "daedalus", None)
        if daedalus is not None:
            raw = str(getattr(daedalus, "doctrine_file", "") or "").strip()
            if raw:
                p = Path(raw).expanduser()
                if not p.is_file():
                    # relative to config.toml directory
                    cfg_path = getattr(config, "path", None)
                    if cfg_path is not None:
                        cand = (Path(cfg_path).resolve().parent / raw).resolve()
                        if cand.is_file():
                            return cand
                    # relative to package
                    cand = (Path(__file__).resolve().parent.parent.parent / raw).resolve()
                    if cand.is_file():
                        return cand
                else:
                    return p
    if _PACKAGE_DOCTRINE.is_file():
        return _PACKAGE_DOCTRINE
    return None


def doctrine_enabled(config=None) -> bool:
    env = os.environ.get("WALLBREAKER_DOCTRINE")
    if env is not None:
        return env.strip().lower() not in ("0", "false", "off", "no")
    if config is not None:
        daedalus = getattr(config, "daedalus", None)
        if daedalus is not None:
            return bool(getattr(daedalus, "doctrine_enabled", True))
    # default on when package doctrine exists (Daedalus product default)
    return _PACKAGE_DOCTRINE.is_file()


def load_doctrine_text(config=None) -> str:
    if not doctrine_enabled(config):
        return ""
    path = resolve_doctrine_path(config)
    if path is None:
        return ""
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def is_same_doctrine_file(path: str | Path | None, config=None) -> bool:
    """True when path already points at the doctrine file (avoid double-inject)."""
    if not path:
        return False
    try:
        a = Path(path).expanduser().resolve()
    except OSError:
        return False
    doctrine = resolve_doctrine_path(config)
    if doctrine is None:
        return False
    try:
        return a == doctrine.resolve()
    except OSError:
        return False
