from __future__ import annotations

from ._common import BaseLoader

DATASET_URL = (
    "https://raw.githubusercontent.com/llm-attacks/llm-attacks/main/"
    "data/advbench/harmful_behaviors.csv"
)


class AdvBenchLoader(BaseLoader):
    name = "advbench"
    url = DATASET_URL
    cache_filename = "advbench_harmful_behaviors.csv"
    benign = False

    def normalize(self, row: dict, idx: int, benign: bool) -> dict | None:
        behavior = (row.get("goal") or "").strip()
        if not behavior:
            return None
        out = {
            "id": f"advbench-{idx}",
            "behavior": behavior,
            "category": "advbench",
            "source": self.name,
            "benign": benign,
        }
        target = (row.get("target") or "").strip()
        if target:
            out["prefill"] = target
        return out
