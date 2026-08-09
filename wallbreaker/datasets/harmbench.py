from __future__ import annotations

from .. import harmbench as _hb


class HarmBenchLoader:
    name = "harmbench"

    def is_cached(self) -> bool:
        return _hb.is_cached()

    def load(self) -> list[dict]:
        return [dict(r, source="harmbench", benign=False) for r in _hb.load_behaviors()]

    def categories(self) -> list[str]:
        return _hb.categories()

    def sample(self, category=None, n: int = 8, seed: int = 0, *, benign: bool | None = None) -> list[dict]:
        # HarmBench has no benign split; benign=True -> empty.
        if benign is True:
            return []
        return [dict(r, source="harmbench", benign=False) for r in _hb.sample(category, n, seed)]

    async def ensure(self, offline: bool = False) -> str | None:
        return await _hb.ensure(offline)

    async def battery(
        self,
        category=None,
        n: int = 8,
        seed: int = 0,
        *,
        benign: bool | None = None,
    ) -> list[str] | None:
        if benign is True:
            return []
        return await _hb.battery(category, n, seed)
