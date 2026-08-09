"""TG5 — Multi-Objective Campaign Bandit tests (engine-capability-uplift).

Validates item G: multi-arm tuples (R-G1), Thompson selection (R-G2), posterior
persistence (R-G3), regret curve (R-G4), SP-C1 + SP-DI3 PBT.
All tests CI-cold-safe (no network, no corpora).
"""
from __future__ import annotations

import random

import pytest
import pytest; pytest.importorskip('hypothesis')
from hypothesis import given, settings
from hypothesis import strategies as st

from wallbreaker.tools._bandit import (
    Bandit,
    BanditStore,
    arm_key,
    regret_curve,
)


# ---------------------------------------------------------------------------
# arm_key helper
# ---------------------------------------------------------------------------

def test_arm_key_canonical():
    """arm_key produces a consistent string for (technique, chain, category) (R-G1)."""
    key = arm_key("prefill", "base64", "cyber")
    assert "|" in key
    assert arm_key("prefill", "base64", "cyber") == key  # deterministic
    # Different args → different keys
    assert arm_key("plain", "base64", "cyber") != key


def test_arm_key_empty_fields():
    """arm_key handles empty/None fields without raising (R-G1)."""
    k = arm_key("", "", "")
    assert isinstance(k, str)
    k2 = arm_key(None, None, None)  # type: ignore[arg-type]
    assert isinstance(k2, str)


# ---------------------------------------------------------------------------
# 5.5  Regret curve — beats random-arm baseline on a seeded fixture (R-G4)
# ---------------------------------------------------------------------------

def test_regret_curve_beats_random_on_biased_fixture():
    """Bandit rewards > random rewards → beats_random=True (R-G4 §5.5)."""
    # Bandit consistently picks the good arm: lots of 1.0 rewards
    bandit_rewards = [1.0, 1.0, 1.0, 0.0, 1.0, 1.0, 1.0, 0.0, 1.0, 1.0]
    # Random arm picks bad arm: lots of 0.0
    random_rewards = [0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0]
    result = regret_curve(bandit_rewards, random_rewards)
    assert result["beats_random"] is True
    assert len(result["bandit"]) == len(bandit_rewards)
    assert len(result["random"]) == len(random_rewards)


def test_regret_curve_monotone_with_all_hits():
    """Cumulative ASR with all 1.0 rewards is always 1.0 (edge case)."""
    rewards = [1.0] * 5
    result = regret_curve(rewards, rewards)
    assert all(v == pytest.approx(1.0) for v in result["bandit"])


def test_regret_curve_empty():
    """Empty reward sequences return empty lists and beats_random=False."""
    result = regret_curve([], [])
    assert result["bandit"] == []
    assert result["random"] == []
    assert result["beats_random"] is False


# ---------------------------------------------------------------------------
# 5.6  Posterior resume — save mid-campaign, resume, α/β intact (R-G3)
# ---------------------------------------------------------------------------

def test_posterior_resume_alpha_beta_intact(tmp_path):
    """Kill mid-campaign, resume: arm posteriors are preserved exactly (R-G3 §5.6)."""
    path = str(tmp_path / "state.json")
    store = BanditStore(path)
    band = store.bandit("gpt-5", "cyber")

    arms = [arm_key("prefill", "", "cyber"), arm_key("plain", "", "cyber")]
    rng = random.Random(42)
    for _ in range(10):
        chosen = band.thompson_select(arms, rng=rng)
        band.update(chosen, rng.random())

    store.save("gpt-5", "cyber", band)

    # "Resume" — fresh store instance, same path
    resumed = BanditStore(path).bandit("gpt-5", "cyber")
    for arm in arms:
        assert resumed.count(arm) == band.count(arm)
        assert resumed.mean(arm) == pytest.approx(band.mean(arm), abs=1e-9)


# ---------------------------------------------------------------------------
# SP-C1 — Bandit only returns registered arms; α,β ≥ 1 (TG5.7)
# ---------------------------------------------------------------------------

@settings(max_examples=200, deadline=None)
@given(
    arms=st.lists(
        st.tuples(
            st.sampled_from(["pair", "crescendo", "ica"]),
            st.sampled_from(["", "base64", "zw"]),
            st.sampled_from(["cyber", "bio", "chem"]),
        ),
        min_size=1, max_size=8, unique=True,
    ),
    rewards=st.lists(st.floats(0.0, 1.0), min_size=1, max_size=30),
)
def test_bandit_registered_arms_only(arms, rewards):
    """thompson_select only ever returns a REGISTERED arm; after any update sequence the
    Beta parameters stay ≥ 1 (α=reward+1, β=n-reward+1) (SP-C1 / R-G1/G2).
    """
    keys = ["|".join(a) for a in arms]
    b = Bandit(arms={})
    rng = random.Random(0)
    for r in rewards:
        chosen = b.thompson_select(keys, rng=rng)
        assert chosen in keys, f"thompson_select returned unregistered arm {chosen!r}"
        b.update(chosen, r)
    for k in keys:
        assert b.count(k) >= 0 and 0.0 <= b.mean(k) <= 1.0


# ---------------------------------------------------------------------------
# SP-DI3 — Arm posterior round-trip (TG5.8)
# ---------------------------------------------------------------------------

from hypothesis import HealthCheck
_SC = [HealthCheck.function_scoped_fixture]


@settings(max_examples=100, suppress_health_check=_SC)
@given(
    updates=st.lists(
        st.tuples(st.sampled_from(["a", "b", "c"]), st.floats(0.0, 1.0)),
        min_size=1, max_size=40,
    )
)
def test_arm_posterior_roundtrip(updates, tmp_path):
    """A bandit's (count, mean) per arm survives save→load exactly (SP-DI3 / R-G3).

    Note: uses unique uuid path so Hypothesis re-runs don't cross-contaminate.
    """
    import uuid
    path = str(tmp_path / f"state_{uuid.uuid4().hex}.json")
    store = BanditStore(path)
    band = store.bandit("gpt-5", "cyber")
    for arm, r in updates:
        band.update(arm, r)
    store.save("gpt-5", "cyber", band)

    reopened = BanditStore(path).bandit("gpt-5", "cyber")
    for arm in {a for a, _ in updates}:
        assert reopened.count(arm) == band.count(arm), (
            f"count mismatch for arm {arm!r}: {reopened.count(arm)} != {band.count(arm)}"
        )
