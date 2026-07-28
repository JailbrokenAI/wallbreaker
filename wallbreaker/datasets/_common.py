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


def filter_behaviors(
    behaviors: list[dict],
    *,
    category=None,
    benign: bool | None = None,
) -> list[dict]:
    """Filter rows by category and/or benign flag.

    ``benign=None`` keeps both harmful and benign rows.
    ``benign=True`` is the over-refusal / FRR denominator (JailbreakBench benign, etc.).
    ``benign=False`` is the attack ASR numerator pool.
    """
    out = list(behaviors or [])
    if category is not None and str(category).strip():
        cat = str(category).strip()
        out = [b for b in out if str(b.get("category") or "") == cat]
    if benign is not None:
        want = bool(benign)
        out = [b for b in out if bool(b.get("benign")) is want]
    return out


def stratified_sample(
    behaviors: list[dict],
    category=None,
    n: int = 8,
    seed: int = 0,
    *,
    benign: bool | None = None,
) -> list[dict]:
    pool = filter_behaviors(behaviors, category=category, benign=benign)
    if not pool:
        return []
    rng = random.Random(seed)
    if category:
        rng.shuffle(pool)
        return pool[:n]
    by_cat: dict[str, list] = {}
    for b in pool:
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

    def refresh_blocking(self, *, force: bool = False) -> str | None:
        """Re-download remote sources into the library cache.

        ``force=True`` deletes existing cache files first so a stale mirror is replaced.
        Bundled offline samples (sorrybench/xstest) are never deleted.
        Returns an error string or None on success / nothing-to-fetch.
        """
        errors: list[str] = []
        fetched = 0
        for pos, (url, filename, _benign) in enumerate(self._sources()):
            if not url:
                continue
            path = cache_path(filename)
            if force and path.is_file():
                try:
                    path.unlink()
                except OSError as exc:
                    errors.append(f"{filename}: cannot clear ({exc})")
                    continue
            if path.is_file() and not force:
                continue
            err = download(url, path, label=self.name)
            if err:
                errors.append(err)
            else:
                fetched += 1
        if errors and fetched == 0:
            return "; ".join(errors)
        return None

    async def refresh(self, *, force: bool = False) -> str | None:
        return await asyncio.to_thread(self.refresh_blocking, force=force)

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

    def sample(
        self,
        category=None,
        n: int = 8,
        seed: int = 0,
        *,
        benign: bool | None = None,
    ) -> list[dict]:
        return stratified_sample(self.load(), category, n, seed, benign=benign)

    def sample_rows(
        self,
        category=None,
        n: int = 8,
        seed: int = 0,
        *,
        benign: bool | None = None,
    ) -> list[dict]:
        """Alias of sample() that makes the full row (incl. benign flag) explicit."""
        return self.sample(category=category, n=n, seed=seed, benign=benign)

    async def battery(
        self,
        category=None,
        n: int = 8,
        seed: int = 0,
        *,
        benign: bool | None = None,
    ) -> list[str] | None:
        err = await self.ensure()
        if err or not self.is_cached():
            return None
        rows = self.sample(category, n, seed, benign=benign)
        if not rows:
            return None
        return [b["behavior"] for b in rows]
