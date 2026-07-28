"""SORRY-Bench style multi-category refusal battery.

Uses a vendored 44-category sample under ``library/sorrybench_sample.csv`` so
campaigns work offline, and optionally refreshes from a remote CSV when present.
"""

from __future__ import annotations

from pathlib import Path

from ._common import BaseLoader, library_dir


# Community mirror / raw export locations vary; keep URL configurable via the
# standard cache refresh path. Offline sample is authoritative for tests.
REMOTE_URL = (
    "https://raw.githubusercontent.com/SORRY-Bench/SORRY-Bench/main/"
    "data/sorry_bench.csv"
)


class SorryBenchLoader(BaseLoader):
    name = "sorrybench"
    url = REMOTE_URL
    cache_filename = "sorrybench.csv"
    benign = False

    def bundled_path(self) -> Path:
        """Prefer package fixtures (tracked); fall back to gitignored library/."""
        pkg = Path(__file__).resolve().parent / "fixtures" / "sorrybench_sample.csv"
        if pkg.is_file():
            return pkg
        return library_dir() / "sorrybench_sample.csv"

    def is_cached(self) -> bool:
        return self.cache_path().is_file() or self.bundled_path().is_file()

    def _ensure_blocking(self) -> str | None:
        err = super()._ensure_blocking()
        if self.cache_path().is_file() or self.bundled_path().is_file():
            return None
        return err or "sorrybench not cached and no bundled sample present."

    def load(self) -> list[dict]:
        from ._common import parse_csv

        rows: list[dict] = []
        seen: set[str] = set()
        for path in (self.cache_path(), self.bundled_path()):
            if not path.is_file():
                continue
            text = path.read_text(encoding="utf-8")
            for norm in parse_csv(text, lambda r, i: self.normalize(r, i, False)):
                key = (norm.get("behavior") or "").strip().lower()
                if not key or key in seen:
                    continue
                seen.add(key)
                norm.setdefault("source", self.name)
                rows.append(norm)
        return rows

    def normalize(self, row: dict, idx: int, benign: bool) -> dict | None:
        behavior = (
            row.get("prompt")
            or row.get("question")
            or row.get("query")
            or row.get("behavior")
            or row.get("Goal")
            or ""
        ).strip()
        if not behavior:
            return None
        category = (
            row.get("category")
            or row.get("Category")
            or row.get("taxonomy")
            or "sorrybench"
        ).strip() or "sorrybench"
        flag = str(row.get("benign") or "").strip().lower()
        is_benign = bool(benign)
        if flag in ("true", "1", "yes"):
            is_benign = True
        elif flag in ("false", "0", "no"):
            is_benign = False
        return {
            "id": f"sorrybench-{idx}",
            "behavior": behavior,
            "category": category,
            "source": self.name,
            "benign": is_benign,
        }

    def categories(self) -> list[str]:
        return sorted({b["category"] for b in self.load()})
