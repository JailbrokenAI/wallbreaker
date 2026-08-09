"""Bandit defaults on for recommend_transforms / seed_sweep."""

from pathlib import Path


def test_recommend_and_seed_bandit_default_true():
    rec = Path("wallbreaker/tools/recommend.py").read_text(encoding="utf-8")
    seed = Path("wallbreaker/tools/seed_sweep.py").read_text(encoding="utf-8")
    assert 'args.get("bandit", True)' in rec
    assert 'args.get("bandit", True)' in seed
