from __future__ import annotations

import asyncio
import csv
import io
import random
from pathlib import Path

import httpx


def library_dir() -> Path:
    return Path(__file__).resolve().parent.parent.parent / "library"


def cache_path(filename: str) -> Path:
    return library_dir() / filename


def download(url: str, path: Path, label: str = "dataset") -> str | None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        resp = httpx.get(url, timeout=30, follow_redirects=True)
        if resp.status_code != 200:
            return f"{label} download failed: HTTP {resp.status_code}"
        path.write_text(resp.text, encoding="utf-8")
        return None
    except httpx.HTTPError as exc:
        return f"{label} download failed: {exc}"


def parse_csv(text: str, mapper) -> list[dict]:
    rows: list[dict] = []
    reader = csv.DictReader(io.StringIO(text))
    for idx, raw in enumerate(reader):
        clean = {(k or "").strip(): (v or "") for k, v in raw.items()}
        norm = mapper(clean, idx)
        if norm and norm.get("behavior"):
            rows.append(norm)
    return rows


def stratified_sample(behaviors: list[dict], category=None, n: int = 8, seed: int = 0) -> list[dict]:
    if not behaviors:
        return []
    rng = random.Random(seed)
    if category:
        pool = [b for b in behaviors if b["category"] == category]
        rng.shuffle(pool)
        return pool[:n]
    by_cat: dict[str, list] = {}
    for b in behaviors:
        by_cat.setdefault(b["category"], []).append(b)
    for lst in by_cat.values():
        rng.shuffle(lst)
    out: list[dict] = []
    cats = sorted(by_cat)
    rng.shuffle(cats)
    i = 0
    while len(out) < n and any(by_cat[c] for c in cats):
        c = cats[i % len(cats)]
        if by_cat[c]:
            out.append(by_cat[c].pop())
        i += 1
    return out[:n]


class BaseLoader:
    name = ""
    url = ""
    cache_filename = ""
    benign = False
    extra_sources: tuple = ()

    def _sources(self):
        yield (self.url, self.cache_filename, self.benign)
        for src in self.extra_sources:
            yield src

    def cache_path(self) -> Path:
        return cache_path(self.cache_filename)

    def is_cached(self) -> bool:
        return self.cache_path().is_file()

    def normalize(self, row: dict, idx: int, benign: bool) -> dict | None:
        raise NotImplementedError

    def _ensure_blocking(self) -> str | None:
        primary_err = None
        for pos, (url, filename, _benign) in enumerate(self._sources()):
            path = cache_path(filename)
            if path.is_file():
                continue
            err = download(url, path, label=self.name)
            if err and pos == 0:
                primary_err = err
        return primary_err

    async def ensure(self, offline: bool = False) -> str | None:
        if self.is_cached():
            return None
        if offline:
            return f"{self.name} not cached and offline."
        return await asyncio.to_thread(self._ensure_blocking)

    def load(self) -> list[dict]:
        rows: list[dict] = []
        for url, filename, benign in self._sources():
            path = cache_path(filename)
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            for norm in parse_csv(text, lambda r, i, b=benign: self.normalize(r, i, b)):
                norm.setdefault("source", self.name)
                rows.append(norm)
        return rows

    def categories(self) -> list[str]:
        return sorted({b["category"] for b in self.load()})

    def sample(self, category=None, n: int = 8, seed: int = 0) -> list[dict]:
        return stratified_sample(self.load(), category, n, seed)

    async def battery(self, category=None, n: int = 8, seed: int = 0) -> list[str] | None:
        err = await self.ensure()
        if err or not self.is_cached():
            return None
        rows = self.sample(category, n, seed)
        if not rows:
            return None
        return [b["behavior"] for b in rows]
