"""TG3 — Target-Family Routing tests (engine-capability-uplift).

Validates item D: classify_family totality (R-D1), family-seeded bandit (R-D2),
best-technique-by-family for /stats (R-D3), SP-IV1 PBT.
All tests are CI-cold-safe (no network, no corpora).
"""
from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from wallbreaker.tools.campaign import classify_family


# ---------------------------------------------------------------------------
# 3.4  Focused — known model strings map to expected families
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("model,expected_family", [
    # OpenAI
    ("gpt-5",                              "openai"),
    ("openai/gpt-4o-mini",                "openai"),
    ("chatgpt-4o",                         "openai"),
    ("o3-mini",                            "openai"),
    ("o1-preview",                         "openai"),
    # Anthropic
    ("anthropic/claude-4-sonnet",         "anthropic"),
    ("claude-3.7-sonnet",                 "anthropic"),
    ("claude-4",                          "anthropic"),
    # Google
    ("google/gemini-2.0-flash",           "google"),
    ("gemini-1.5-pro",                    "google"),
    ("palm-2",                            "google"),
    # DeepSeek
    ("deepseek/deepseek-chat",            "deepseek"),
    ("deepseek-r1",                       "deepseek"),
    # Meta / Llama
    ("meta-llama/Llama-3.1-70B",         "meta"),
    ("llama-3-8b",                        "meta"),
    ("mistral-7b",                        "meta"),
    ("mixtral-8x7b",                      "meta"),
    # Other
    ("unknown-model-xyz",                 "other"),
    ("",                                  "other"),
    ("   ",                               "other"),
])
def test_classify_family_known_models(model, expected_family):
    """Known model strings map to the expected family (§3.4 / R-D1)."""
    assert classify_family(model) == expected_family


# ---------------------------------------------------------------------------
# 3.5  SP-IV1 — PBT family classifier totality
# ---------------------------------------------------------------------------

_KNOWN_FAMILIES = frozenset({"openai", "anthropic", "google", "deepseek", "meta", "other"})

_MODEL_STRINGS = st.one_of(
    st.sampled_from([
        "gpt-5", "openai/gpt-4o-mini", "anthropic/claude-4-sonnet", "claude-3.7-sonnet",
        "deepseek/deepseek-chat", "meta-llama/Llama-3.1-70B", "google/gemini-2.0-flash",
        "", "   ", "??weird//name", "модель-кириллица", "x" * 300,
    ]),
    st.text(max_size=40),
)


@settings(max_examples=400)
@given(model=_MODEL_STRINGS)
def test_family_classifier_total(model):
    """classify_family is TOTAL, deterministic: every string → exactly one known family,
    never raises (SP-IV1 / R-D1).
    """
    fam = classify_family(model)
    assert fam in _KNOWN_FAMILIES
    assert classify_family(model) == fam  # deterministic


# ---------------------------------------------------------------------------
# 3.6  Unknown → "other", never a crash
# ---------------------------------------------------------------------------

def test_unknown_model_returns_other():
    """Unknown model strings map to 'other' (§3.6)."""
    assert classify_family("some-unknown-vendor/weird-model-99") == "other"
    assert classify_family("") == "other"
    assert classify_family("   ") == "other"
    assert classify_family(None) == "other"  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 3.2 / 3.7  Family-seeded bandit (R-D2) — seed only when no live data exists
# ---------------------------------------------------------------------------

def test_family_prior_seeds_bandit_when_no_live_data(tmp_path):
    """seed_family_priors injects empirical wins when the bucket is cold (R-D2)."""
    from wallbreaker.tools._bandit import ContextualBandit, seed_family_priors

    cb = ContextualBandit()
    priors = {"openai": {"prefill": (4.0, 2.0), "plain": (1.0, 5.0)}}
    seed_family_priors(cb, "openai", "default", priors)

    # After seeding: prefill should have a higher posterior mean than plain
    assert cb.mean(("openai", "default"), "prefill") > cb.mean(("openai", "default"), "plain")


def test_family_prior_does_not_overwrite_live_data(tmp_path):
    """seed_family_priors skips when live data already exists (§3.7)."""
    from wallbreaker.tools._bandit import ContextualBandit, seed_family_priors

    cb = ContextualBandit()
    context = ("openai", "default")
    # Inject live data first: plain wins 3 times
    for _ in range(3):
        cb.update(context, "plain", 1.0)
    original_mean = cb.mean(context, "plain")

    priors = {"openai": {"prefill": (10.0, 2.0), "plain": (0.0, 10.0)}}
    seed_family_priors(cb, "openai", "default", priors)

    # Live data must be unchanged — seeding skipped
    assert cb.mean(context, "plain") == original_mean


def test_family_prior_uniform_fallback_for_unknown_family():
    """Unknown families (no prior) fall back to uniform — no error (§3.7)."""
    from wallbreaker.tools._bandit import ContextualBandit, seed_family_priors

    cb = ContextualBandit()
    seed_family_priors(cb, "other", "default", {})  # no prior for "other"
    # Bucket should remain empty (uniform prior = no pre-seeding)
    assert not cb.has_stats(("other", "default"))


# ---------------------------------------------------------------------------
# 3.3 / R-D3  best_technique_by_family — /stats surface
# ---------------------------------------------------------------------------

def test_best_technique_by_family_returns_correct_structure(tmp_path):
    """best_technique_by_family reads saved bandit state and returns {family: {cat: tech}}."""
    import json as _json
    from wallbreaker.tools._bandit import ContextualBandit, best_technique_by_family, context_key

    # Build a contextual bandit with known winners per family
    cb = ContextualBandit()
    for _ in range(5):
        cb.update(("openai", "cyber"), "prefill", 1.0)
    for _ in range(2):
        cb.update(("openai", "cyber"), "plain", 0.0)
    for _ in range(4):
        cb.update(("anthropic", "default"), "narrate", 1.0)

    path = str(tmp_path / "stats.json")
    with open(path, "w") as fh:
        _json.dump(
            {
                context_key("openai", "cyber"):     cb.to_dict()[context_key("openai", "cyber")],
                context_key("anthropic", "default"): cb.to_dict()[context_key("anthropic", "default")],
            },
            fh,
        )

    result = best_technique_by_family(path)
    assert result.get("openai", {}).get("cyber") == "prefill"
    assert result.get("anthropic", {}).get("default") == "narrate"


def test_best_technique_by_family_empty_when_no_data(tmp_path):
    """Returns empty dict when no bandit state exists (§3.3)."""
    from wallbreaker.tools._bandit import best_technique_by_family
    path = str(tmp_path / "no_stats.json")
    result = best_technique_by_family(path)
    assert result == {}
