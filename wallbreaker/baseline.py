from __future__ import annotations

import json
from pathlib import Path

from .report import _load_records, asr_by_technique


def load_asr(run_path: str | Path) -> dict[str, dict]:
    records = _load_records(run_path)
    verdicts = [r for r in records if r.get("kind") == "verdict"]
    detailed = asr_by_technique(verdicts)
    return {
        technique: {"hits": stats["strict_hits"], "total": stats["total"]}
        for technique, stats in detailed.items()
    }


def _ratio(bucket: dict) -> float:
    total = bucket.get("total", 0)
    return (bucket.get("hits", 0) / total) if total else 0.0


def baseline_data(run_path: str | Path) -> dict:
    by_tech = load_asr(run_path)
    return {
        "log": str(run_path),
        "asr_by_technique": {
            t: {"hits": b["hits"], "total": b["total"], "asr": _ratio(b)}
            for t, b in by_tech.items()
        },
    }


def save_baseline(run_path: str | Path, out_path: str | Path) -> dict:
    data = baseline_data(run_path)
    out = Path(out_path)
    if out.parent and not out.parent.exists():
        out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return data


def _baseline_ratios(data: dict) -> dict[str, float]:
    by_tech = data.get("asr_by_technique", {})
    ratios: dict[str, float] = {}
    for t, b in by_tech.items():
        if isinstance(b, dict):
            ratios[t] = b.get("asr", _ratio(b))
        else:
            ratios[t] = float(b)
    return ratios


def compare_baseline(
    run_path: str | Path,
    baseline_path: str | Path,
    max_regression: float = 0.05,
) -> tuple[bool, list[dict]]:
    base = json.loads(Path(baseline_path).read_text(encoding="utf-8"))
    base_ratios = _baseline_ratios(base)
    current = load_asr(run_path)

    regressions: list[dict] = []
    for tech, bucket in current.items():
        cur = _ratio(bucket)
        prev = base_ratios.get(tech, 0.0)
        delta = cur - prev
        if delta > max_regression:
            regressions.append(
                {
                    "technique": tech,
                    "baseline": prev,
                    "current": cur,
                    "delta": delta,
                    "hits": bucket["hits"],
                    "total": bucket["total"],
                }
            )
    regressions.sort(key=lambda r: -r["delta"])
    return (not regressions, regressions)


def format_regressions(
    regressions: list[dict], ok: bool, max_regression: float
) -> str:
    if ok:
        return f"ASR within tolerance (max regression {max_regression:.0%}); no regressions."
    lines = [
        f"ASR REGRESSION: {len(regressions)} technique(s) rose by more than "
        f"{max_regression:.0%} vs baseline:",
    ]
    for r in regressions:
        lines.append(
            f"  {r['technique']}: {r['baseline']:.0%} -> {r['current']:.0%} "
            f"(+{r['delta']:.0%}, {r['hits']}/{r['total']})"
        )
    return "\n".join(lines)
