from __future__ import annotations

from .. import harmbench as _hb


class HarmBenchLoader:
    name = "harmbench"

    def is_cached(self) -> bool:
        return _hb.is_cached()

    def load(self) -> list[dict]:
        return [dict(r, source="harmbench") for r in _hb.load_behaviors()]

    def categories(self) -> list[str]:
        return _hb.categories()

    def sample(self, category=None, n: int = 8, seed: int = 0) -> list[dict]:
        return [dict(r, source="harmbench") for r in _hb.sample(category, n, seed)]

    async def ensure(self, offline: bool = False) -> str | None:
        return await _hb.ensure(offline)

    async def battery(self, category=None, n: int = 8, seed: int = 0) -> list[str] | None:
        return await _hb.battery(category, n, seed)
