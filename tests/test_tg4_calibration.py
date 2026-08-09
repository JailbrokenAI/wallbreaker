"""TG4 — Judge-Ensemble Calibration tests (engine-capability-uplift).

Validates item E (build-upon): _compute_ensemble_agreement, >20% alert, single-judge
unaffected.  Pure unit tests — no network calls, no judge endpoint required.
(spec tasks.md §4.3, §4.4, §4.5)
"""
from __future__ import annotations

import pytest

from wallbreaker.tools.judge_selftest import (
    FIXTURES,
    _compute_ensemble_agreement,
)


# ---------------------------------------------------------------------------
# _compute_ensemble_agreement unit tests
# ---------------------------------------------------------------------------

def test_full_agreement_gives_kappa_1():
    """When all members give the same labels, kappa=1 and all disagree_rates=0."""
    labels_a = ["COMPLIED", "REFUSED", "PARTIAL"] * 3
    labels_b = ["COMPLIED", "REFUSED", "PARTIAL"] * 3
    kappa, rates = _compute_ensemble_agreement([labels_a, labels_b])
    assert kappa == pytest.approx(1.0)
    assert all(r == 0.0 for r in rates)


def test_full_disagreement_gives_kappa_0():
    """When two members always disagree, kappa=0 and the losing member has rate=1."""
    labels_a = ["COMPLIED", "COMPLIED", "COMPLIED"]
    labels_b = ["REFUSED", "REFUSED", "REFUSED"]
    kappa, rates = _compute_ensemble_agreement([labels_a, labels_b])
    assert kappa == pytest.approx(0.0)
    # Tie-break goes to member_a (COMPLIED < REFUSED alphabetically),
    # so member_a has rate=0, member_b has rate=1.
    assert max(rates) == pytest.approx(1.0)


def test_single_member_always_agrees():
    """Single-member ensemble: kappa=1, disagree_rate=0 (§4.5 — single-judge default)."""
    labels = ["COMPLIED", "REFUSED", "PARTIAL"]
    kappa, rates = _compute_ensemble_agreement([labels])
    assert kappa == pytest.approx(1.0)
    assert rates == [0.0]


def test_partial_disagreement():
    """One member disagrees on 1 of 4 fixtures → disagree_rate = 0.25."""
    labels_a = ["COMPLIED", "REFUSED", "PARTIAL", "COMPLIED"]
    labels_b = ["COMPLIED", "REFUSED", "PARTIAL", "REFUSED"]  # disagrees on last
    _kappa, rates = _compute_ensemble_agreement([labels_a, labels_b])
    # member_b disagrees on 1/4 = 25%
    assert rates[1] == pytest.approx(0.25)


def test_empty_gives_no_crash():
    """Empty per_member_labels returns 1.0 kappa, empty rates."""
    kappa, rates = _compute_ensemble_agreement([])
    assert kappa == pytest.approx(1.0)
    assert rates == []


# ---------------------------------------------------------------------------
# 4.3  Negative control — miscalibrated stub trips the >20% alert
# ---------------------------------------------------------------------------

def test_miscalibrated_judge_trips_alert():
    """A member that disagrees >20% of the time triggers the alert (§4.3 / R-E2)."""
    n = len(FIXTURES)
    # Member A gives majority labels; Member B disagrees on 30% (> 20% threshold)
    agree_labels = ["COMPLIED"] * n
    bad_labels = list(agree_labels)
    # Flip 30% of labels to something else
    for i in range(int(n * 0.30) + 1):
        bad_labels[i] = "REFUSED"

    kappa, rates = _compute_ensemble_agreement([agree_labels, bad_labels])
    # At least one member's rate should exceed 20%
    assert any(r > 0.20 for r in rates), (
        f"Expected at least one member with >20% disagreement, got rates={rates}"
    )


# ---------------------------------------------------------------------------
# 4.4  Positive control — well-behaved ensemble passes (<= 20% each)
# ---------------------------------------------------------------------------

def test_well_behaved_ensemble_passes():
    """Members agreeing on all but 1 fixture (< 20%) should NOT trigger alert (§4.4)."""
    n = max(len(FIXTURES), 10)
    labels_a = ["COMPLIED"] * n
    labels_b = list(labels_a)
    labels_b[0] = "REFUSED"  # exactly 1/n disagreement < 20% for n >= 6

    _kappa, rates = _compute_ensemble_agreement([labels_a, labels_b])
    assert all(r <= 0.20 for r in rates), (
        f"Expected all rates ≤ 20% but got {rates}"
    )


# ---------------------------------------------------------------------------
# 4.5  Single-judge default unaffected
# ---------------------------------------------------------------------------

def test_single_judge_no_ensemble_section(tmp_path):
    """When no ensemble arg is passed, the selftest output has no ensemble section."""
    import asyncio
    from wallbreaker.config import Config, Endpoint
    from wallbreaker.tools.judge_selftest import _judge_selftest
    from wallbreaker.tools.registry import ToolContext

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    ctx = ToolContext(config=cfg, judge_endpoint=ep)

    # Monkeypatch grade to avoid network
    import wallbreaker.tools.judge_selftest as jst_mod
    import wallbreaker.judging as judging_mod

    original_grade = judging_mod.grade

    async def _stub_grade(endpoint, response, **kwargs):
        return ("COMPLIED", 9, "stub", "stub")

    judging_mod.grade = _stub_grade
    try:
        result = asyncio.run(_judge_selftest({}, ctx))
    finally:
        judging_mod.grade = original_grade

    assert "ENSEMBLE CALIBRATION" not in result
    assert "EXIT: non-zero" not in result


def test_compute_ensemble_agreement_three_members():
    """Three-member ensemble with one outlier: only the outlier should exceed 20%."""
    n = 10
    majority = ["COMPLIED"] * n
    match = list(majority)
    outlier = list(majority)
    # Outlier disagrees on 4/10 = 40%
    for i in range(4):
        outlier[i] = "REFUSED"

    kappa, rates = _compute_ensemble_agreement([majority, match, outlier])
    # The outlier (index 2) should have the highest disagreement rate
    assert rates[2] > 0.20
    # The matching members (0 and 1) should have low disagreement
    assert rates[0] <= 0.20
    assert rates[1] <= 0.20
