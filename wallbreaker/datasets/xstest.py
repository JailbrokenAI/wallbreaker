"""XSTest-style over-refusal / benign prompt battery.

Primary source is the vendored ``library/xstest_benign_prompts.csv`` so FRR
scans work offline. Optional remote fetch can refresh the cache later.
"""

from __future__ import annotations

from pathlib import Path

from ._common import BaseLoader, cache_path, library_dir


# Public XSTest v2 prompts (Röttger et al.). Used when network is available to
# refresh the local cache; offline path always falls back to the vendored sample.
REMOTE_URL = (
    "https://raw.githubusercontent.com/paul-rottger/xstest/main/"
    "data/xstest_v2_prompts.csv"
)


class XSTestLoader(BaseLoader):
    """Benign / partial-risk prompts for over-refusal (FRR) measurement."""

    name = "xstest"
    url = REMOTE_URL
    cache_filename = "xstest_prompts.csv"
    benign = True  # default rows are the FRR denominator

    def bundled_path(self) -> Path:
        """Prefer package fixtures (tracked); fall back to gitignored library/."""
        pkg = Path(__file__).resolve().parent / "fixtures" / "xstest_benign_prompts.csv"
        if pkg.is_file():
            return pkg
        return library_dir() / "xstest_benign_prompts.csv"

    def is_cached(self) -> bool:
        return self.cache_path().is_file() or self.bundled_path().is_file()

    def _ensure_blocking(self) -> str | None:
        # Prefer remote refresh into cache; bundled sample is always a fallback.
        err = super()._ensure_blocking()
        if self.cache_path().is_file() or self.bundled_path().is_file():
            return None
        return err or "xstest not cached and no bundled sample present."

    def load(self) -> list[dict]:
        rows: list[dict] = []
        # Remote/cache first, then bundled sample (may overlap; de-dupe by behavior).
        paths = []
        cached = self.cache_path()
        if cached.is_file():
            paths.append((cached, False))  # may mix labels
        bundled = self.bundled_path()
        if bundled.is_file():
            paths.append((bundled, True))
        seen: set[str] = set()
        from ._common import parse_csv

        for path, force_benign in paths:
            text = path.read_text(encoding="utf-8")
            for norm in parse_csv(
                text, lambda r, i, fb=force_benign: self.normalize(r, i, fb)
            ):
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
            or row.get("Prompt")
            or row.get("question")
            or row.get("Goal")
            or ""
        ).strip()
        if not behavior:
            return None
        # XSTest uses label in {benign, contrast, ...}; treat non-harm as benign.
        raw_label = (row.get("label") or row.get("type") or "").strip().lower()
        category = (
            row.get("category")
            or row.get("Category")
            or row.get("type")
            or "xstest"
        ).strip() or "xstest"
        if "label" in row or "type" in row:
            is_benign = raw_label in (
                "",
                "benign",
                "safe",
                "partial_risk",
                "partial-risk",
                "homonym",
                "homonyms",
                "figurative",
                "real_benign",
                "defensive",
                "contrast_benign",
            )
            # explicit harmful labels
            if raw_label in ("harmful", "unsafe", "contrast", "full_risk", "full-risk"):
                is_benign = False
        else:
            is_benign = bool(benign) if isinstance(benign, bool) else True
            # CSV may carry a benign column
            flag = str(row.get("benign") or "").strip().lower()
            if flag in ("true", "1", "yes"):
                is_benign = True
            elif flag in ("false", "0", "no"):
                is_benign = False
        return {
            "id": f"xstest-{idx}",
            "behavior": behavior,
            "category": category,
            "source": self.name,
            "benign": is_benign,
        }
