"""Product-layer display branding (Daedalus) vs package identity (wallbreaker).

The installable package, CLI entry point, import path, and GitHub repo stay
``wallbreaker`` for compatibility. User-facing chrome (dashboard, desktop shell,
TUI banners, notify titles) reads the configurable Daedalus codename.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .config import Config

DEFAULT_CODENAME = "Daedalus"
DEFAULT_TAGLINE_ZH = "授权红队评估工作台"
DEFAULT_TAGLINE_EN = "Authorized red-team evaluation workbench"


def product_codename(config: "Config | None" = None) -> str:
    """Return the operator-facing product name (default Daedalus)."""
    if config is not None:
        d = getattr(config, "daedalus", None)
        name = str(getattr(d, "codename", "") or "").strip()
        if name:
            return name
    return DEFAULT_CODENAME


def product_mark(config: "Config | None" = None) -> str:
    """Short rail mark from the codename (e.g. Daedalus -> D)."""
    name = product_codename(config)
    return (name[:1] or "D").upper()


def product_wordmark_parts(config: "Config | None" = None) -> tuple[str, str]:
    """Split codename into (prefix, emphasis) for stylized wordmarks.

    ``Daedalus`` -> ("DAE", "DALUS"); single-token short names put the whole
    string in the emphasis half.
    """
    name = product_codename(config)
    raw = name.strip()
    if not raw:
        return ("DAE", "DALUS")
    # Prefer a natural mid split for multi-syllable names.
    # Prefer a readable split for known codenames; else ~40/60.
    lower = raw.lower()
    if lower == "daedalus":
        return ("DAE", "DALUS")
    if lower == "wallbreaker":
        return ("WALL", "BREAKER")
    if len(raw) >= 6:
        mid = max(3, len(raw) * 2 // 5)
        return (raw[:mid].upper(), raw[mid:].upper())
    return ("", raw.upper())


def cli_description(config: "Config | None" = None) -> str:
    codename = product_codename(config)
    return (
        f"{codename} — red-team harness (package: wallbreaker): "
        "a configurable agentic LLM terminal"
    )


def desktop_product_name(config: "Config | None" = None) -> str:
    return f"{product_codename(config)} Desktop"


def notify_title(config: "Config | None" = None, event: str = "") -> str:
    base = product_codename(config)
    event = (event or "").strip()
    return f"{base} · {event}" if event else base
