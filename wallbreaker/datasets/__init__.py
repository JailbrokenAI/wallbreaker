from __future__ import annotations

from .advbench import AdvBenchLoader
from .harmbench import HarmBenchLoader
from .jbb import JBBLoader
from .sorrybench import SorryBenchLoader
from .strongreject import StrongRejectLoader

DATASETS = {
    "harmbench": HarmBenchLoader(),
    "jbb": JBBLoader(),
    "strongreject": StrongRejectLoader(),
    "advbench": AdvBenchLoader(),
    "sorrybench": SorryBenchLoader(),
}


def sources() -> list[str]:
    return sorted(DATASETS)


def get(source: str | None = "harmbench"):
    key = (source or "harmbench").lower()
    loader = DATASETS.get(key)
    if loader is None:
        raise KeyError(
            f"unknown dataset '{source}'. Known sources: {', '.join(sources())}"
        )
    return loader


def load(source: str | None = "harmbench") -> list[dict]:
    return get(source).load()


def categories(source: str | None = "harmbench") -> list[str]:
    return get(source).categories()


def sample(source: str | None = "harmbench", category=None, n: int = 8, seed: int = 0) -> list[dict]:
    return get(source).sample(category, n, seed)


async def battery(source: str | None = "harmbench", category=None, n: int = 8, seed: int = 0) -> list[str] | None:
    return await get(source).battery(category, n, seed)


__all__ = [
    "DATASETS",
    "sources",
    "get",
    "load",
    "categories",
    "sample",
    "battery",
]
