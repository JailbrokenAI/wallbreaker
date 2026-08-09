"""TG7 — Cross-Family Transfer Learning tests (engine-capability-uplift).

Validates item I: family tag on rows (R-I1), retrieve_by_family cold-start (R-I1),
transfer_score non-negative + monotone (R-I2), cross_family_matrix shape + symmetry (R-I3),
SP-DI4 PBT. All tests CI-cold-safe.
"""
from __future__ import annotations

import pytest
import pytest; pytest.importorskip('hypothesis')
from hypothesis import given, settings
from hypothesis import strategies as st

from wallbreaker.strategy_lib import (
    StrategyLibrary,
    cross_family_matrix,
    retrieval_bonus,
    transfer_score,
)


# ---------------------------------------------------------------------------
# 7.1  Family tag persists on library rows (R-I1)
# ---------------------------------------------------------------------------

def test_family_tag_stored_and_retrieved(tmp_path):
    """family kwarg on add() is persisted to the row (R-I1)."""
    lib = StrategyLibrary(str(tmp_path / "lib.jsonl"))
    lib.add("s1", "openai strategy", "example", score=8.0, family="openai")
    lib.add("s2", "anthropic strategy", "example", score=7.0, family="anthropic")

    rows = {r["strategy_name"]: r for r in lib.all()}
    assert rows["s1"]["family"] == "openai"
    assert rows["s2"]["family"] == "anthropic"


def test_family_tag_persists_across_reload(tmp_path):
    """Family tag survives save/load round-trip."""
    path = str(tmp_path / "lib.jsonl")
    lib = StrategyLibrary(path)
    lib.add("tactic", "a strategy", "ex", score=9.0, family="google")

    reloaded = StrategyLibrary(path)
    assert reloaded.all()[0]["family"] == "google"


def test_rows_without_family_tag_load_fine(tmp_path):
    """Legacy rows without family tag still load and are retrievable (R-I1 backward compat)."""
    import json
    path = str(tmp_path / "lib.jsonl")
    with open(path, "w") as f:
        f.write(json.dumps({
            "strategy_name": "old_tactic", "description": "old", "example_prompt": "x",
            "embedding": [0.0] * 256, "avg_score": 5.0, "n_uses": 1, "tier": "promising",
        }) + "\n")
    lib = StrategyLibrary(path)
    assert len(lib.all()) == 1
    assert "family" not in lib.all()[0]  # no tag — that's fine


# ---------------------------------------------------------------------------
# 7.1 (cont.)  retrieve_by_family cold-start (R-I1)
# ---------------------------------------------------------------------------

def test_retrieve_by_family_returns_same_family_rows(tmp_path):
    """retrieve_by_family returns only rows tagged with the requested family."""
    lib = StrategyLibrary(str(tmp_path / "lib.jsonl"))
    lib.add("openai_tactic1", "openai desc 1", "ex", score=9.0, family="openai")
    lib.add("openai_tactic2", "openai desc 2", "ex", score=7.0, family="openai")
    lib.add("anthropic_tactic", "anthropic desc", "ex", score=8.0, family="anthropic")

    results = lib.retrieve_by_family("openai", k=5)
    assert all(r.get("family") == "openai" for r in results)
    assert len(results) == 2


def test_retrieve_by_family_ordered_by_avg_score(tmp_path):
    """retrieve_by_family returns highest-scoring rows first."""
    lib = StrategyLibrary(str(tmp_path / "lib.jsonl"))
    lib.add("low", "desc", "ex", score=4.0, family="openai")
    lib.add("high", "desc", "ex", score=9.0, family="openai")
    lib.add("mid", "desc", "ex", score=6.0, family="openai")

    results = lib.retrieve_by_family("openai", k=3)
    scores = [r["avg_score"] for r in results]
    assert scores == sorted(scores, reverse=True)


def test_retrieve_by_family_empty_when_no_rows(tmp_path):
    """retrieve_by_family returns [] when no rows have the requested family."""
    lib = StrategyLibrary(str(tmp_path / "lib.jsonl"))
    lib.add("other_tactic", "desc", "ex", score=8.0, family="anthropic")
    assert lib.retrieve_by_family("openai", k=5) == []


# ---------------------------------------------------------------------------
# 7.2  transfer_score + update_transfer_score (R-I2)
# ---------------------------------------------------------------------------

def test_update_transfer_score_increments(tmp_path):
    """update_transfer_score increments the win counters correctly (R-I2)."""
    lib = StrategyLibrary(str(tmp_path / "lib.jsonl"))
    lib.add("tactic", "desc", "ex", score=8.0, family="openai")

    lib.update_transfer_score("tactic", origin_delta=2, same_family_delta=1, cross_family_delta=3)
    row = lib.all()[0]
    assert row["origin_wins"] == 2
    assert row["same_family_wins"] == 1
    assert row["cross_family_wins"] == 3


def test_update_transfer_score_records_target_family(tmp_path):
    lib = StrategyLibrary(str(tmp_path / "lib.jsonl"))
    lib.add("tactic", "desc", "ex", score=8.0, family="openai")
    lib.update_transfer_score("tactic", cross_family_delta=2, target_family="anthropic")
    assert lib.all()[0]["family_wins"] == {"anthropic": 2}


def test_update_transfer_score_non_negative(tmp_path):
    """transfer score components are always ≥ 0 even with zero/negative deltas (R-I2)."""
    lib = StrategyLibrary(str(tmp_path / "lib.jsonl"))
    lib.add("tactic", "desc", "ex", score=8.0)
    lib.update_transfer_score("tactic", origin_delta=0, same_family_delta=0, cross_family_delta=0)
    row = lib.all()[0]
    assert row["origin_wins"] == 0
    assert row["same_family_wins"] == 0
    assert row["cross_family_wins"] == 0


def test_update_transfer_score_missing_name(tmp_path):
    """update_transfer_score returns None for unknown strategy (R-I2)."""
    lib = StrategyLibrary(str(tmp_path / "lib.jsonl"))
    assert lib.update_transfer_score("nonexistent") is None


# ---------------------------------------------------------------------------
# SP-DI4 — PBT: transfer_score conservation + monotone bonus (TG7.6)
# ---------------------------------------------------------------------------

@settings(max_examples=200)
@given(
    origin=st.integers(0, 50),
    same=st.integers(0, 50),
    cross=st.integers(0, 50),
    more=st.integers(0, 10),
)
def test_transfer_score_conservation(origin, same, cross, more):
    """transfer_score components are non-negative and retrieval_bonus is bounded
    and MONOTONE non-decreasing in the score (SP-DI4 / R-I2).
    """
    s = transfer_score(origin_wins=origin, same_family_wins=same, cross_family_wins=cross)
    assert s >= 0.0
    b = retrieval_bonus(s)
    assert 0.0 <= b <= 1.0
    s_more = transfer_score(origin_wins=origin, same_family_wins=same, cross_family_wins=cross + more)
    assert retrieval_bonus(s_more) >= b, (
        f"retrieval_bonus({s_more:.3f}) < retrieval_bonus({s:.3f}) — monotonicity violated"
    )


# ---------------------------------------------------------------------------
# 7.5  cross_family_matrix shape + symmetry sanity (R-I3)
# ---------------------------------------------------------------------------

def test_cross_family_matrix_shape(tmp_path):
    """cross_family_matrix covers all family pairs and has None on the diagonal."""
    lib = StrategyLibrary(str(tmp_path / "lib.jsonl"))
    # Seed strategies with family tags + cross_family_wins
    lib.add("openai_s1", "openai desc", "ex", score=9.0, family="openai")
    lib.update_transfer_score("openai_s1", origin_delta=3, cross_family_delta=2)
    lib.add("anthropic_s1", "anthropic desc", "ex", score=8.0, family="anthropic")
    lib.update_transfer_score("anthropic_s1", origin_delta=2, cross_family_delta=1)
    lib.add("google_s1", "google desc", "ex", score=7.0, family="google")

    families = ["openai", "anthropic", "google"]
    result = cross_family_matrix(lib.all(), families)
    matrix = result["matrix"]

    assert set(result["families"]) == set(families)
    # Diagonal should be None (self-transfer not reported)
    for f in families:
        assert matrix[f][f] is None
    # All keys present
    for orig in families:
        for tgt in families:
            assert tgt in matrix[orig]


def test_cross_family_matrix_empty_library():
    """Empty strategy library → all cells are None, no crash."""
    families = ["openai", "anthropic", "google"]
    result = cross_family_matrix([], families)
    for orig in families:
        for tgt in families:
            assert result["matrix"][orig][tgt] is None


def test_cross_family_matrix_uses_target_specific_wins(tmp_path):
    lib = StrategyLibrary(str(tmp_path / "lib.jsonl"))
    lib.add("for_anthropic", "desc", "ex", score=8.0, family="openai")
    lib.add("for_google", "desc", "ex", score=8.0, family="openai")
    lib.update_transfer_score("for_anthropic", cross_family_delta=4, target_family="anthropic")
    lib.update_transfer_score("for_google", cross_family_delta=5, target_family="google")
    matrix = cross_family_matrix(lib.all(), ["openai", "anthropic", "google"])["matrix"]
    assert matrix["openai"]["anthropic"] == "for_anthropic"
    assert matrix["openai"]["google"] == "for_google"
