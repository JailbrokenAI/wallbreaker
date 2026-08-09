from __future__ import annotations

from .advbench import AdvBenchLoader
from .harmbench import HarmBenchLoader
from .jbb import JBBLoader
from .sorrybench import SorryBenchLoader
from .strongreject import StrongRejectLoader
from .xstest import XSTestLoader

DATASETS = {
    "harmbench": HarmBenchLoader(),
    "jbb": JBBLoader(),
    "strongreject": StrongRejectLoader(),
    "advbench": AdvBenchLoader(),
    "sorrybench": SorryBenchLoader(),
    "xstest": XSTestLoader(),
}


def sources() -> list[str]:
    return sorted(DATASETS)


_ALIASES = {
    "sorry": "sorrybench",
    "sorry-bench": "sorrybench",
    "sorry_bench": "sorrybench",
    "xs": "xstest",
    "xstest-benign": "xstest",
    "overrefusal": "xstest",
    "frr": "xstest",
}


def get(source: str | None = "harmbench"):
    key = (source or "harmbench").lower().strip()
    key = _ALIASES.get(key, key)
    loader = DATASETS.get(key)
    if loader is None:
        raise KeyError(
            f"unknown dataset '{source}'. Known sources: {', '.join(sources())}"
        )
    return loader


def load(
    source: str | None = "harmbench",
    *,
    benign: bool | None = None,
) -> list[dict]:
    """Load cached rows. ``benign=True/False`` filters the FRR / ASR split."""
    from ._common import filter_behaviors

    rows = get(source).load()
    if benign is None:
        return rows
    return filter_behaviors(rows, benign=benign)


def categories(source: str | None = "harmbench", *, benign: bool | None = None) -> list[str]:
    rows = load(source, benign=benign)
    return sorted({b["category"] for b in rows if b.get("category")})


def sample(
    source: str | None = "harmbench",
    category=None,
    n: int = 8,
    seed: int = 0,
    *,
    benign: bool | None = None,
) -> list[dict]:
    return get(source).sample(category, n, seed, benign=benign)


async def battery(
    source: str | None = "harmbench",
    category=None,
    n: int = 8,
    seed: int = 0,
    *,
    benign: bool | None = None,
) -> list[str] | None:
    """Behavior strings for a battery. Pass ``benign=True`` for the FRR denominator."""
    return await get(source).battery(category, n, seed, benign=benign)


def has_benign(source: str | None = "harmbench") -> bool:
    """True when the source exposes at least one cached benign row (e.g. JBB)."""
    try:
        return any(bool(r.get("benign")) for r in get(source).load())
    except Exception:
        return False


def status(source: str | None = None) -> list[dict]:
    """Operator-facing cache status for one or all dataset sources."""
    names = [source] if source else sources()
    out: list[dict] = []
    for name in names:
        try:
            loader = get(name)
        except KeyError:
            continue
        cached = False
        try:
            cached = bool(loader.is_cached())
        except Exception:
            cached = False
        try:
            n = len(loader.load())
        except Exception:
            n = 0
        try:
            n_benign = sum(1 for r in loader.load() if r.get("benign"))
        except Exception:
            n_benign = 0
        out.append(
            {
                "source": name,
                "cached": cached,
                "rows": n,
                "benign_rows": n_benign,
                "has_benign": n_benign > 0,
            }
        )
    return out


async def refresh(source: str | None = None, *, force: bool = False) -> dict[str, str | None]:
    """Refresh remote dataset caches. ``source=None`` refreshes every registered loader."""
    names = [source] if source else sources()
    results: dict[str, str | None] = {}
    for name in names:
        try:
            loader = get(name)
        except KeyError as exc:
            results[str(name)] = str(exc)
            continue
        refresh_fn = getattr(loader, "refresh", None)
        if refresh_fn is None:
            results[name] = "refresh not supported"
            continue
        try:
            results[name] = await refresh_fn(force=force)
        except Exception as exc:  # noqa: BLE001
            results[name] = str(exc)
    return results


__all__ = [
    "DATASETS",
    "sources",
    "get",
    "load",
    "categories",
    "sample",
    "battery",
    "has_benign",
]
