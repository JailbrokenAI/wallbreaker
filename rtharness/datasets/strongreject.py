from __future__ import annotations

from ._common import BaseLoader

DATASET_URL = (
    "https://raw.githubusercontent.com/alexandrasouly/strongreject/main/"
    "strongreject_dataset/strongreject_dataset.csv"
)


class StrongRejectLoader(BaseLoader):
    name = "strongreject"
    url = DATASET_URL
    cache_filename = "strongreject_dataset.csv"
    benign = False

    def normalize(self, row: dict, idx: int, benign: bool) -> dict | None:
        behavior = (row.get("forbidden_prompt") or "").strip()
        if not behavior:
            return None
        category = (row.get("category") or "strongreject").strip() or "strongreject"
        return {
            "id": f"strongreject-{idx}",
            "behavior": behavior,
            "category": category,
            "source": self.name,
            "benign": benign,
        }
