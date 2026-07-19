from __future__ import annotations

import hashlib
import json
import os

from ._fsutil import atomic_write

# Cache file format versions (RACE-2).
#   v1 (legacy, pre-TG5.3): each JSONL line is a CUMULATIVE snapshot of the running total
#     for a key. Replay kept the last line per key. Multi-process interleaved writes could
#     undercount (last writer wins a smaller total).
#   v2 (TG5.3): each line is a DELTA (one sample). Replay sums deltas. A sub-PIPE_BUF line
#     appended in "a" mode is atomic on POSIX, so multi-process append is safe without a lock.
# The loader is tolerant of both: it keeps the last v1 snapshot per key and adds v2 deltas on
# top, so existing v1 files keep working (migrated in place as new v2 deltas append).
_FORMAT_VERSION = 2
# Compact the cache file to one cumulative line per key once it grows past this many lines
# (bounded growth, RACE-2). Compaction is a derived optimization: the append-only deltas are
# the source of truth, and a crash mid-compaction loses nothing (the temp file is abandoned).
_COMPACTION_THRESHOLD = 5000


def _serialize_messages(messages) -> list:
    out = []
    for m in messages or []:
        role = getattr(m, "role", None)
        text_fn = getattr(m, "text", None)
        if role is not None and callable(text_fn):
            try:
                text = text_fn()
            except Exception:
                text = ""
            out.append([str(role), str(text)])
        elif isinstance(m, dict):
            out.append([str(m.get("role", "")), str(m.get("content", ""))])
        else:
            out.append(["", str(m)])
    return out


def _norm_label(label) -> str:
    low = str(label or "").strip().lower()
    if low.startswith("compl"):
        return "complied"
    if low.startswith("part"):
        return "partial"
    return "refused"


def _blank() -> dict:
    return {
        "samples": 0,
        "complied": 0,
        "partial": 0,
        "refused": 0,
        "last_response": "",
        "last_label": "",
    }


class ResultCache:
    """Read-through verdict cache for repeated target fires.

    Keyed by sha1 of the serialized request (messages, transform chain, target
    model, system prompt, max_tokens). Persists every put as one JSONL line under
    cwd/wb_runs/result_cache.jsonl and keeps an in-memory index; a fresh instance
    replays the file so the cache survives across calls and sessions.
    """

    FILENAME = "result_cache.jsonl"

    def __init__(self, cwd: str = "."):
        self.cwd = cwd or "."
        outdir = os.path.join(os.path.abspath(self.cwd), "wb_runs")
        self.path = os.path.join(outdir, self.FILENAME)
        self._index: dict[str, dict] = {}
        self._load()

    def _load(self) -> None:
        """Replay the cache file. Tolerant of both formats (RACE-2):
          - v1 lines (no ``v`` field, or ``v == 1``): cumulative snapshots — keep the LAST one
            per key (legacy behaviour).
          - v2 lines (``v == 2``): deltas — sum them per key.
        A key's final entry = (last v1 snapshot) + (sum of v2 deltas). An old file with new
        v2 deltas appended therefore migrates correctly (no double-count)."""
        # Per-key: the last v1 snapshot seen, and the running sum of v2 deltas.
        snapshots: dict[str, dict] = {}
        deltas: dict[str, dict] = {}
        line_count = 0
        try:
            with open(self.path, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    line_count += 1
                    try:
                        rec = json.loads(line)
                    except (ValueError, TypeError):
                        continue
                    key = rec.get("key")
                    if not key:
                        continue
                    if rec.get("v") == _FORMAT_VERSION:
                        # v2 delta: +1 sample, +1 in the bucket this put landed in.
                        d = deltas.setdefault(key, {"samples": 0, "complied": 0, "partial": 0, "refused": 0})
                        d["samples"] += int(rec.get("ds", 0) or 0)
                        bucket = _norm_label(rec.get("dbucket"))
                        if bucket in ("complied", "partial", "refused"):
                            d[bucket] += 1
                        # Track the most-recent last_response/last_label from deltas too.
                        deltas[key]["last_response"] = str(rec.get("last_response", "") or "")
                        deltas[key]["last_label"] = str(rec.get("last_label", "") or "")
                    else:
                        # v1 (legacy) cumulative snapshot — last one wins for this key.
                        entry = _blank()
                        for field in ("samples", "complied", "partial", "refused"):
                            entry[field] = int(rec.get(field, 0) or 0)
                        entry["last_response"] = str(rec.get("last_response", "") or "")
                        entry["last_label"] = str(rec.get("last_label", "") or "")
                        snapshots[key] = entry
        except OSError:
            return
        # Merge: final = snapshot + deltas.
        keys = set(snapshots) | set(deltas)
        for key in keys:
            entry = dict(snapshots.get(key) or _blank())
            d = deltas.get(key)
            if d:
                entry["samples"] = int(entry.get("samples", 0)) + d["samples"]
                entry["complied"] = int(entry.get("complied", 0)) + d["complied"]
                entry["partial"] = int(entry.get("partial", 0)) + d["partial"]
                entry["refused"] = int(entry.get("refused", 0)) + d["refused"]
                if d.get("last_response") or d.get("last_label"):
                    entry["last_response"] = d["last_response"]
                    entry["last_label"] = d["last_label"]
            self._index[key] = entry
        self._line_count = line_count

    @staticmethod
    def make_key(
        messages,
        transform_chain=None,
        target_model: str = "",
        system=None,
        max_tokens: int = 0,
    ) -> str:
        payload = {
            "messages": _serialize_messages(messages),
            "transform_chain": [str(t) for t in (transform_chain or [])],
            "target_model": str(target_model or ""),
            "system": "" if system is None else str(system),
            "max_tokens": int(max_tokens or 0),
        }
        blob = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha1(blob.encode("utf-8")).hexdigest()

    def get(self, key: str):
        entry = self._index.get(key)
        return dict(entry) if entry is not None else None

    def put(self, key: str, label: str, response: str) -> dict:
        entry = self._index.get(key) or _blank()
        entry["samples"] = int(entry.get("samples", 0)) + 1
        bucket = _norm_label(label)
        entry[bucket] = int(entry.get(bucket, 0)) + 1
        entry["last_response"] = response or ""
        entry["last_label"] = str(label or "")
        self._index[key] = entry
        self._append_delta(key, label, response)
        return dict(entry)

    def _append_delta(self, key: str, label: str, response: str) -> None:
        """Append a single v2 delta line (one sample). POSIX append of a small line is atomic,
        so multi-process append is safe without a lock (RACE-2)."""
        try:
            os.makedirs(os.path.dirname(self.path), exist_ok=True)
            rec = {
                "key": key, "v": _FORMAT_VERSION, "ds": 1,
                "dbucket": _norm_label(label),
                "last_response": response or "", "last_label": str(label or ""),
            }
            with open(self.path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            self._line_count = getattr(self, "_line_count", 0) + 1
            if self._line_count >= _COMPACTION_THRESHOLD:
                self._compact()
        except OSError:
            pass

    def _compact(self) -> None:
        """Rewrite the cache as one cumulative line per key (v1 snapshot form) via the atomic
        write helper, bounding on-disk growth (RACE-2). The append-only deltas are the source
        of truth; a crash mid-compaction loses nothing (the temp file is abandoned and the
        original is untouched until os.replace). A concurrent append that lands during
        compaction writes to the now-unlinked old inode and is an acknowledged rare, low-
        severity loss (one cached sample — the cache is not the system of record)."""
        try:
            lines = []
            for key, entry in self._index.items():
                lines.append(json.dumps({"key": key, **entry}, ensure_ascii=False))
            text = "\n".join(lines) + ("\n" if lines else "")
            atomic_write(self.path, text)
            self._line_count = len(lines)
        except OSError:
            pass
