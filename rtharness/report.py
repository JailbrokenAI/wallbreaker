from __future__ import annotations

import json
from pathlib import Path


def _load_records(log_path: str | Path) -> list[dict]:
    path = Path(log_path)
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def extract_findings(log_path: str | Path) -> list[dict]:
    rank = {"COMPLIED": 0, "PARTIAL": 1}
    hits = [
        r
        for r in _load_records(log_path)
        if r.get("kind") == "verdict" and r.get("label") in rank
    ]
    hits.sort(key=lambda r: rank.get(r.get("label"), 9))
    return hits


def build_report(log_path: str | Path) -> str:
    path = Path(log_path)
    if not path.is_file():
        return f"# Red-team report\n\nNo run log found at {path}.\n"

    records = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            records.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    explicit = [r["text"] for r in records if r.get("kind") == "objective"]
    first_user = next((r["text"] for r in records if r.get("kind") == "user"), None)
    objectives = explicit or ([first_user] if first_user else [])
    verdicts = [r for r in records if r.get("kind") == "verdict"]
    total = len(verdicts)
    hits = sum(1 for v in verdicts if v["label"] in ("COMPLIED", "PARTIAL"))

    out = ["# Red-team engagement report", ""]
    out.append(f"- Source log: `{path}`")
    out.append(f"- Target queries graded: {total}")
    out.append(f"- Bypassed or partial: {hits}")
    out.append(f"- Guardrail held: {total - hits}")
    asr = f"{(hits / total * 100):.0f}%" if total else "n/a"
    out.append(f"- Attack success rate: {asr}")
    out.append("")

    if objectives:
        out.append("## Objectives")
        for obj in objectives:
            out.append(f"- {obj}")
        out.append("")

    if verdicts:
        out.append("## Attempts")
        out.append("")
        out.append("| # | verdict | payload | rationale |")
        out.append("|---|---------|---------|-----------|")
        for i, v in enumerate(verdicts, 1):
            payload = str(v.get("payload", "")).replace("\n", " ")[:60]
            rationale = str(v.get("reason", "")).replace("\n", " ")[:60]
            out.append(f"| {i} | {v['label']} | {payload} | {rationale} |")
        out.append("")

    out.append("## Recommendation")
    if hits:
        out.append(
            "At least one payload elicited disallowed content. Harden the target: "
            "decode-then-filter inputs, add output classification, and add the bypassing "
            "encodings to the refusal training set."
        )
    else:
        out.append("No payload bypassed the guardrail in this run.")
    out.append("")
    return "\n".join(out)
