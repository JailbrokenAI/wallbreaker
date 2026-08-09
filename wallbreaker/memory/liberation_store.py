"""Global Liberation Memory — successful unlock prompts for later REPLAY.

Scope is global (library/liberation/) per product decision. Records are keyed by
id and indexed lightly by model + tags + objective tokens for cold retrieval.

Similarity ranking (``find_similar``):
  - **token** — Jaccard on word tokens (always available)
  - **embed** — offline hashed bag-of-token + char-ngram vectors (no external
    model; disabled with ``WALLBREAKER_MEMORY_EMBED=0``)
  - **hybrid** (default) — blend of token + embed, with model boost

External embedding providers plug in via ``embed_fn`` (see ``memory.embedders``
``build_embed_fn`` for OpenAI/OpenRouter/custom). Offline hash remains the
default so REPLAY works with zero network.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

_SLUG_RE = re.compile(r"[^a-z0-9]+")
_TOKEN_RE = re.compile(r"[a-z0-9]{3,}")

# Fixed-dim offline embedding (hashed features). Stable across processes.
_EMBED_DIM = 256
_NGRAM_N = 3


def default_memory_root(cwd: str | Path | None = None) -> Path:
    base = Path(cwd) if cwd else Path.cwd()
    return (base / "library" / "liberation").resolve()


def _slug(text: str, limit: int = 80) -> str:
    s = _SLUG_RE.sub("-", (text or "").strip().lower()).strip("-")
    return (s[:limit].rstrip("-") if len(s) > limit else s) or "misc"


def _tokens(text: str) -> set[str]:
    return set(_TOKEN_RE.findall((text or "").lower()))


def _now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def token_overlap_score(query: str, document: str) -> float:
    """Jaccard-style overlap of query tokens against document tokens.

    Score is ``|q ∩ d| / |q|`` so short queries against rich documents still rank.
    """
    q = _tokens(query)
    if not q:
        return 0.0
    d = _tokens(document)
    if not d:
        return 0.0
    return len(q & d) / max(1, len(q))


def _feature_hashes(text: str) -> list[int]:
    """Stable feature ids from word tokens and char n-grams."""
    raw = (text or "").lower()
    feats: list[int] = []
    for tok in _TOKEN_RE.findall(raw):
        h = int(hashlib.sha1(f"t:{tok}".encode("utf-8")).hexdigest()[:8], 16)
        feats.append(h)
    # char n-grams on alnum-only stream for morphology (encrypt≈encryption)
    compact = re.sub(r"[^a-z0-9]+", "", raw)
    if len(compact) >= _NGRAM_N:
        for i in range(len(compact) - _NGRAM_N + 1):
            gram = compact[i : i + _NGRAM_N]
            h = int(hashlib.sha1(f"g:{gram}".encode("utf-8")).hexdigest()[:8], 16)
            feats.append(h)
    return feats


def hashed_embed(text: str, dim: int = _EMBED_DIM) -> list[float]:
    """Offline bag-of-features embedding via feature hashing (no model download).

    L2-normalized. Empty text → zero vector.
    """
    dim = max(8, int(dim))
    vec = [0.0] * dim
    feats = _feature_hashes(text)
    if not feats:
        return vec
    for h in feats:
        idx = h % dim
        sign = 1.0 if (h & 1) == 0 else -1.0
        vec[idx] += sign
    norm = math.sqrt(sum(v * v for v in vec))
    if norm <= 0:
        return vec
    return [v / norm for v in vec]


def _l2_normalize(vec: list[float]) -> list[float] | None:
    """Return a unit vector, or None if the input is zero / empty."""
    if not vec:
        return None
    norm = math.sqrt(sum(float(v) * float(v) for v in vec))
    if norm <= 0.0:
        return None
    return [float(v) / norm for v in vec]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Cosine similarity in [-1, 1]. Always L2-normalizes both sides.

    External ``embed_fn`` outputs need not be unit-length; raw scaled vectors
    (e.g. ``[100, 0]``) must not inflate scores via bare dot product.
    """
    if not a or not b or len(a) != len(b):
        return 0.0
    na = _l2_normalize(list(a))
    nb = _l2_normalize(list(b))
    if na is None or nb is None:
        return 0.0
    dot = float(sum(x * y for x, y in zip(na, nb)))
    # numerical clamp
    if dot > 1.0:
        return 1.0
    if dot < -1.0:
        return -1.0
    return dot


def embed_similarity(query: str, document: str, *, dim: int = _EMBED_DIM) -> float:
    """Cosine similarity of offline hashed embeddings."""
    return cosine_similarity(hashed_embed(query, dim=dim), hashed_embed(document, dim=dim))


def memory_embed_enabled() -> bool:
    """Offline embed assist is on unless WALLBREAKER_MEMORY_EMBED=0/false/off."""
    env = os.environ.get("WALLBREAKER_MEMORY_EMBED")
    if env is not None:
        return env.strip().lower() not in ("0", "false", "off", "no")
    return True


def parse_validate_rate(rate: str) -> float:
    """Parse ``6/8`` or ``75%`` into a fraction in ``[0, 1]``. Empty → 0."""
    raw = (rate or "").strip()
    if not raw:
        return 0.0
    if raw.endswith("%"):
        try:
            return max(0.0, min(1.0, float(raw[:-1].strip()) / 100.0))
        except ValueError:
            return 0.0
    if "/" in raw:
        left, _, right = raw.partition("/")
        try:
            num = float(left.strip())
            den = float(right.strip())
        except ValueError:
            return 0.0
        if den <= 0:
            return 0.0
        return max(0.0, min(1.0, num / den))
    try:
        val = float(raw)
    except ValueError:
        return 0.0
    if val > 1.0:
        # bare percent-like number
        return max(0.0, min(1.0, val / 100.0))
    return max(0.0, min(1.0, val))


def reliability_boost(validate_rate: str = "", hits: int = 0) -> float:
    """Small REPLAY rank bump for validated, frequently re-used wins.

    - validate fraction contributes up to +0.15
    - hit count contributes up to +0.10 (``min(hits, 10) * 0.01``)
    Total boost capped at +0.25 so it cannot drown semantic match.
    """
    frac = parse_validate_rate(validate_rate)
    hit_n = max(0, int(hits or 0))
    hit_term = min(10, hit_n) * 0.01
    return min(0.25, 0.15 * frac + hit_term)


def hybrid_similarity(
    query: str,
    document: str,
    *,
    method: str = "hybrid",
    embed_fn: Callable[[str], list[float]] | None = None,
    token_weight: float = 0.55,
) -> float:
    """Rank score for one (query, document) pair.

    ``method``:
      - token   — token overlap only
      - embed   — embedding cosine only (hashed or ``embed_fn``)
      - hybrid  — weighted blend (default)

    ``embed_fn`` optional external embedder ``text -> vector``; on failure or
    when embed is disabled, hybrid/embed fall back to token.
    """
    method = (method or "hybrid").strip().lower()
    tok = token_overlap_score(query, document)
    if method == "token":
        return tok

    use_embed = memory_embed_enabled()
    emb = 0.0
    if use_embed:
        try:
            if embed_fn is not None:
                qv = embed_fn(query)
                dv = embed_fn(document)
                emb = cosine_similarity(list(qv), list(dv))
            else:
                emb = embed_similarity(query, document)
        except Exception:
            emb = 0.0
            use_embed = False

    if method == "embed":
        return emb if use_embed and emb > 0 else tok

    # hybrid
    if not use_embed or emb <= 0:
        return tok
    tw = min(1.0, max(0.0, float(token_weight)))
    return tw * tok + (1.0 - tw) * emb


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


@dataclass
class LiberationRecord:
    """One successful liberation / unlock that should be replayable."""

    id: str
    objective_norm: str
    tags: list[str] = field(default_factory=list)
    model: str = ""
    mode_path: list[str] = field(default_factory=lambda: ["CODE", "LIBERATE"])
    system_prefix: str = ""
    user_framing: str = ""
    technique: str = ""
    payload: str = ""
    transforms: list[str] = field(default_factory=list)
    validate_rate: str = ""
    judge: str = ""
    artifact_paths: list[str] = field(default_factory=list)
    created_at: str = ""
    hits: int = 0

    @staticmethod
    def make_id(
        objective_norm: str,
        model: str,
        technique: str,
        system_prefix: str,
        user_framing: str,
    ) -> str:
        canon = json.dumps(
            {
                "objective_norm": objective_norm or "",
                "model": model or "",
                "technique": technique or "",
                "system_prefix": system_prefix or "",
                "user_framing": user_framing or "",
            },
            sort_keys=True,
            ensure_ascii=False,
        )
        return hashlib.sha1(canon.encode("utf-8")).hexdigest()[:16]


class LiberationStore:
    """Filesystem-backed global store under ``library/liberation/``.

    Layout::

        library/liberation/
          _catalog.json
          by-model/<model-slug>/rec-<id>.json
    """

    def __init__(self, root: str | Path | None = None, cwd: str | Path | None = None):
        if root:
            self.root = Path(root).expanduser().resolve()
        else:
            self.root = default_memory_root(cwd)
        self.catalog_path = self.root / "_catalog.json"

    def _record_path(self, model: str, rec_id: str) -> Path:
        return self.root / "by-model" / _slug(model or "unknown") / f"rec-{rec_id}.json"

    def save(
        self,
        *,
        objective_norm: str,
        model: str = "",
        tags: list[str] | None = None,
        system_prefix: str = "",
        user_framing: str = "",
        technique: str = "",
        payload: str = "",
        transforms: list[str] | None = None,
        validate_rate: str = "",
        judge: str = "",
        artifact_paths: list[str] | None = None,
        mode_path: list[str] | None = None,
    ) -> LiberationRecord:
        objective_norm = (objective_norm or "").strip()
        if not objective_norm:
            raise ValueError("objective_norm is required")
        rec_id = LiberationRecord.make_id(
            objective_norm, model, technique, system_prefix, user_framing
        )
        path = self._record_path(model, rec_id)
        existing = None
        if path.is_file():
            raw = _read_json(path, None)
            if isinstance(raw, dict):
                existing = raw
        rec = LiberationRecord(
            id=rec_id,
            objective_norm=objective_norm,
            tags=list(tags or []),
            model=model or "",
            mode_path=list(mode_path or ["CODE", "LIBERATE"]),
            system_prefix=system_prefix or "",
            user_framing=user_framing or "",
            technique=technique or "",
            payload=payload or "",
            transforms=list(transforms or []),
            validate_rate=validate_rate or "",
            judge=judge or "",
            artifact_paths=list(artifact_paths or []),
            created_at=(existing or {}).get("created_at") or _now_iso(),
            hits=int((existing or {}).get("hits") or 0),
        )
        _write_json(path, asdict(rec))
        self._upsert_catalog(rec)
        return rec

    def _upsert_catalog(self, rec: LiberationRecord) -> None:
        catalog = _read_json(self.catalog_path, {"version": 1, "records": {}})
        if not isinstance(catalog, dict):
            catalog = {"version": 1, "records": {}}
        records = catalog.setdefault("records", {})
        records[rec.id] = {
            "id": rec.id,
            "objective_norm": rec.objective_norm,
            "tags": rec.tags,
            "model": rec.model,
            "technique": rec.technique,
            "judge": rec.judge,
            "validate_rate": rec.validate_rate,
            "path": str(self._record_path(rec.model, rec.id).relative_to(self.root)).replace(
                "\\", "/"
            ),
            "created_at": rec.created_at,
            "hits": rec.hits,
        }
        catalog["updated_at"] = _now_iso()
        _write_json(self.catalog_path, catalog)

    def get(self, rec_id: str) -> LiberationRecord | None:
        catalog = _read_json(self.catalog_path, {})
        meta = (catalog.get("records") or {}).get(rec_id) if isinstance(catalog, dict) else None
        if not isinstance(meta, dict):
            # brute scan
            for path in self.root.glob("by-model/*/rec-*.json"):
                if path.stem == f"rec-{rec_id}":
                    raw = _read_json(path, None)
                    if isinstance(raw, dict):
                        return LiberationRecord(**{k: raw[k] for k in LiberationRecord.__dataclass_fields__ if k in raw})
            return None
        rel = meta.get("path") or ""
        path = self.root / rel
        raw = _read_json(path, None)
        if not isinstance(raw, dict):
            return None
        fields = LiberationRecord.__dataclass_fields__
        return LiberationRecord(**{k: raw[k] for k in fields if k in raw})

    def find_similar(
        self,
        objective: str,
        *,
        model: str = "",
        limit: int = 5,
        method: str = "hybrid",
        embed_fn: Callable[[str], list[float]] | None = None,
        min_score: float = 0.0,
    ) -> list[tuple[float, LiberationRecord]]:
        """Rank catalog entries for REPLAY.

        Default ``method='hybrid'`` blends token overlap with offline hashed
        embeddings (see module docstring). Pass ``method='token'`` for the
        legacy path. ``embed_fn`` injects an external embedder when available.

        Rank additives (capped so semantics still dominate):
          - model match: +0.25
          - ``reliability_boost(validate_rate, hits)``: up to +0.25

        Entries at or below ``min_score`` drop.
        """
        objective = (objective or "").strip()
        if not objective:
            return []
        catalog = _read_json(self.catalog_path, {})
        records = (catalog.get("records") or {}) if isinstance(catalog, dict) else {}
        scored: list[tuple[float, str]] = []
        model_l = (model or "").lower()
        for rec_id, meta in records.items():
            if not isinstance(meta, dict):
                continue
            blob = " ".join(
                [
                    str(meta.get("objective_norm") or ""),
                    " ".join(meta.get("tags") or []),
                    str(meta.get("technique") or ""),
                ]
            )
            if not blob.strip():
                continue
            score = hybrid_similarity(
                objective,
                blob,
                method=method,
                embed_fn=embed_fn,
            )
            if model_l and str(meta.get("model") or "").lower() == model_l:
                score += 0.25
            score += reliability_boost(
                str(meta.get("validate_rate") or ""),
                int(meta.get("hits") or 0),
            )
            if score <= float(min_score or 0.0):
                continue
            scored.append((score, rec_id))
        scored.sort(key=lambda x: (-x[0], x[1]))
        out: list[tuple[float, LiberationRecord]] = []
        for score, rec_id in scored[: max(1, limit)]:
            rec = self.get(rec_id)
            if rec is not None:
                out.append((score, rec))
        return out

    def mark_hit(self, rec_id: str) -> None:
        rec = self.get(rec_id)
        if rec is None:
            return
        rec.hits = int(rec.hits or 0) + 1
        _write_json(self._record_path(rec.model, rec.id), asdict(rec))
        self._upsert_catalog(rec)

    def stats(self) -> dict[str, Any]:
        """Catalog summary for /memory and dashboard overview."""
        catalog = _read_json(self.catalog_path, {})
        records = (catalog.get("records") or {}) if isinstance(catalog, dict) else {}
        if not isinstance(records, dict):
            records = {}
        n = len(records)
        models: dict[str, int] = {}
        techniques: dict[str, int] = {}
        with_validate = 0
        total_hits = 0
        best_rate = 0.0
        for meta in records.values():
            if not isinstance(meta, dict):
                continue
            m = str(meta.get("model") or "unknown") or "unknown"
            models[m] = models.get(m, 0) + 1
            tech = str(meta.get("technique") or "") or "(none)"
            techniques[tech] = techniques.get(tech, 0) + 1
            rate = parse_validate_rate(str(meta.get("validate_rate") or ""))
            if rate > 0:
                with_validate += 1
            best_rate = max(best_rate, rate)
            total_hits += int(meta.get("hits") or 0)
        top_models = sorted(models.items(), key=lambda x: (-x[1], x[0]))[:8]
        top_tech = sorted(techniques.items(), key=lambda x: (-x[1], x[0]))[:8]
        return {
            "root": str(self.root),
            "count": n,
            "with_validate_rate": with_validate,
            "total_hits": total_hits,
            "best_validate_fraction": round(best_rate, 4),
            "models": [{"model": m, "count": c} for m, c in top_models],
            "techniques": [{"technique": t, "count": c} for t, c in top_tech],
            "updated_at": (catalog.get("updated_at") if isinstance(catalog, dict) else None),
        }

    def list_recent(self, limit: int = 10) -> list[dict[str, Any]]:
        """Newest catalog rows (by created_at desc) for operator inspection."""
        catalog = _read_json(self.catalog_path, {})
        records = (catalog.get("records") or {}) if isinstance(catalog, dict) else {}
        if not isinstance(records, dict):
            return []
        rows: list[dict[str, Any]] = []
        for meta in records.values():
            if isinstance(meta, dict):
                rows.append(dict(meta))
        rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
        out = []
        for row in rows[: max(1, int(limit))]:
            out.append(
                {
                    "id": row.get("id"),
                    "objective_norm": row.get("objective_norm"),
                    "model": row.get("model"),
                    "technique": row.get("technique"),
                    "validate_rate": row.get("validate_rate"),
                    "hits": row.get("hits", 0),
                    "judge": row.get("judge"),
                    "created_at": row.get("created_at"),
                }
            )
        return out

    def replay_block(self, rec: LiberationRecord) -> str:
        """Format a system/user inject block for MODE REPLAY."""
        parts = [
            "Liberation replay:",
            f"objective: {rec.objective_norm}",
            f"model: {rec.model}",
            f"technique: {rec.technique}",
        ]
        if rec.user_framing:
            parts.append(f"user_framing:\n{rec.user_framing}")
        if rec.system_prefix:
            parts.append(f"system_prefix:\n{rec.system_prefix}")
        if rec.payload:
            parts.append(f"payload:\n{rec.payload[:4000]}")
        if rec.transforms:
            parts.append("transforms: " + ", ".join(rec.transforms))
        return "\n\n".join(parts)
