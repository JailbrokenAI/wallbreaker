from __future__ import annotations

from ._common import BaseLoader

HARMFUL_URL = (
    "https://huggingface.co/datasets/JailbreakBench/JBB-Behaviors/resolve/main/"
    "data/behaviors.csv"
)
BENIGN_URL = (
    "https://huggingface.co/datasets/JailbreakBench/JBB-Behaviors/resolve/main/"
    "data/benign_behaviors.csv"
)


class JBBLoader(BaseLoader):
    name = "jbb"
    url = HARMFUL_URL
    cache_filename = "jbb_behaviors.csv"
    benign = False
    extra_sources = ((BENIGN_URL, "jbb_benign_behaviors.csv", True),)

    def normalize(self, row: dict, idx: int, benign: bool) -> dict | None:
        goal = (row.get("Goal") or row.get("Behavior") or row.get("Prompt") or "").strip()
        if not goal:
            return None
        category = (row.get("Category") or "jbb").strip() or "jbb"
        rid = (row.get("Index") or row.get("Behavior") or "").strip() or f"jbb-{idx}"
        return {
            "id": rid,
            "behavior": goal,
            "category": category,
            "source": self.name,
            "benign": benign,
        }
