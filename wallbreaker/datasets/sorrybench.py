from __future__ import annotations

from ._common import BaseLoader

DATASET_URL = (
    "https://huggingface.co/datasets/SillyTilly/SorryBench/resolve/main/"
    "sorry_bench_202406.csv"
)


class SorryBenchLoader(BaseLoader):
    name = "sorrybench"
    url = DATASET_URL
    cache_filename = "sorry_bench_202406.csv"
    benign = False

    def normalize(self, row: dict, idx: int, benign: bool) -> dict | None:
        behavior = (row.get("prompt") or row.get("prompt ") or "").strip()
        if not behavior:
            return None
        raw_cat = (row.get("category") or "").strip()
        category = f"sorry-{raw_cat}" if raw_cat else "sorrybench"
        qid = (row.get("question_id") or row.get("id") or "").strip()
        rid = qid if qid else f"sorrybench-{idx}"
        return {
            "id": rid,
            "behavior": behavior,
            "category": category,
            "source": self.name,
            "benign": benign,
        }
