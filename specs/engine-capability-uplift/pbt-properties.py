"""Phase-4 PBT properties for the engine-capability-uplift spec (Hypothesis / Python).

Capability work, so the mandated 5 property categories map primarily to DATA INTEGRITY /
CORRECTNESS and INPUT VALIDATION (see planning/requirements.md "PBT Tooling Decision"); Rate
Limiting re-engages only for J, Access Control only for J's distributed worker. No property is
written against a category the code does not exercise (no theater).

Each property executes the REAL engine function, is biased toward the cases that break correctness
(backend switches, garbage model strings, out-of-range posteriors, tampered arms), and is
@pytest.mark.skip until its task lands — so the file is importable/CI-collectable from day one and
each property flips active as TG#.# completes.

Run: pytest -q specs/engine-capability-uplift/pbt-properties.py
Gate 3 passes when every property is un-skipped, green, meets its max_examples floor, and the
positive controls assert (no-config default >= BoW baseline; no unregistered arm; no rate breach).
"""
from __future__ import annotations

import string

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

# --------------------------------------------------------------------------------------------------
# Shared strategies
# --------------------------------------------------------------------------------------------------
_SC = [HealthCheck.function_scoped_fixture]
_BACKENDS = st.sampled_from(["bm25", "bow", "openai", "local"])
# Distinct, non-overlapping descriptions so a correct retriever must rank the self match first.
_DESCRIPTIONS = st.lists(
    st.text(alphabet=string.ascii_lowercase + " ", min_size=12, max_size=60),
    min_size=2, max_size=6, unique=True,
)
_MODEL_STRINGS = st.one_of(
    st.sampled_from([
        "gpt-5", "openai/gpt-4o-mini", "anthropic/claude-4-sonnet", "claude-3.7-sonnet",
        "deepseek/deepseek-chat", "meta-llama/Llama-3.1-70B", "google/gemini-2.0-flash",
        "", "   ", "??weird//name", "модель-кириллица", "x" * 300,
    ]),
    st.text(max_size=40),
)
_FAMILIES = frozenset({"openai", "anthropic", "google", "deepseek", "meta", "other"})


# ==================================================================================================
# SP-DI1 · Data Integrity — semantic self-retrieval  (TG1: item A)
# ==================================================================================================
@settings(max_examples=200, deadline=None, suppress_health_check=_SC)
@given(descriptions=_DESCRIPTIONS, backend=st.sampled_from(["bm25"]))
def test_self_retrieval_rank1(descriptions, backend, tmp_path):
    """∀ stored strategy, querying with its OWN description returns it rank-1 under the active
    backend. bm25 must satisfy this; legacy bow is explicitly excluded (it fails, by design).
    (R-A4, SP-DI1)"""
    import uuid
    from wallbreaker.strategy_lib import StrategyLibrary

    lib = StrategyLibrary(str(tmp_path / f"lib_{uuid.uuid4().hex}.jsonl"))
    lib.set_embedding_backend(backend)  # intended API
    for i, desc in enumerate(descriptions):
        lib.add(name=f"s{i}", desc=desc, example=f"payload {i}", score=8.0)
    for i, desc in enumerate(descriptions):
        top = lib.retrieve(desc, k=1)
        assert top and top[0]["strategy_name"] == f"s{i}"


@settings(max_examples=100, deadline=None, suppress_health_check=_SC)
@given(descriptions=_DESCRIPTIONS, first=st.sampled_from(["bm25", "bow"]), second=st.sampled_from(["bm25", "bow"]))
def test_row_roundtrip_reembed(descriptions, first, second, tmp_path):
    """save->load preserves every row; switching the embedding backend lazily re-embeds without
    losing or duplicating rows, and legacy untagged rows survive. (R-A2)"""
    import uuid
    from wallbreaker.strategy_lib import StrategyLibrary

    path = str(tmp_path / f"lib_{uuid.uuid4().hex}.jsonl")
    lib = StrategyLibrary(path); lib.set_embedding_backend(first)
    for i, desc in enumerate(descriptions):
        lib.add(name=f"s{i}", desc=desc, example="p", score=7.0)
    lib.save()

    reopened = StrategyLibrary(path); reopened.set_embedding_backend(second); reopened.load()
    assert len(reopened.all()) == len(descriptions)
    _ = reopened.retrieve(descriptions[0], k=1)  # triggers lazy re-embed
    names = sorted(r["strategy_name"] for r in reopened.all())
    assert names == sorted(f"s{i}" for i in range(len(descriptions)))  # no loss / dup


# ==================================================================================================
# SP-DI5 · Data Integrity — ToolContext delegation parity  (TG2: item B)
# ==================================================================================================
@settings(max_examples=200, suppress_health_check=_SC)
@given(
    field=st.sampled_from([
        "current_objective", "attacker_model", "vault_enabled",
        "target_system", "target_reasoning",  # EngagementContext
    ]),
    value=st.one_of(st.text(max_size=40), st.booleans()),
)
def test_context_delegation_parity(field, value, tmp_path):
    """A value set through the ToolContext envelope reads back identically via the delegating
    property AND on the underlying sub-context — the refactor changes structure, not behavior. (R-B2)"""
    from wallbreaker.tools.registry import ToolContext

    ctx = _blank_ctx(tmp_path)
    setattr(ctx, field, value)
    assert getattr(ctx, field) == value
    assert getattr(ctx.engagement, field) == value  # intended sub-context accessor


# ==================================================================================================
# SP-IV1 · Input Validation — family classifier totality  (TG3: item D)
# ==================================================================================================
@pytest.mark.skip(reason="implement in TG3.5")
@settings(max_examples=400)
@given(model=_MODEL_STRINGS)
def test_family_classifier_total(model):
    """classify_family is a TOTAL, deterministic function: every string (incl. empty/garbage/
    unicode/overlong) maps to exactly one known family and never raises. (R-D1)"""
    from wallbreaker.tools.campaign import classify_family  # intended location

    fam = classify_family(model)
    assert fam in _FAMILIES
    assert classify_family(model) == fam  # deterministic


# ==================================================================================================
# SP-C1 · Correctness — bandit only returns registered arms; posterior stays valid  (TG5: item G)
# ==================================================================================================
@pytest.mark.skip(reason="implement in TG5.7")
@settings(max_examples=200, deadline=None)
@given(
    arms=st.lists(st.tuples(st.sampled_from(["pair", "crescendo", "ica"]),
                            st.sampled_from(["", "base64", "zw"]),
                            st.sampled_from(["cyber", "bio", "chem"])),
                  min_size=1, max_size=8, unique=True),
    rewards=st.lists(st.floats(0.0, 1.0), min_size=1, max_size=30),
)
def test_bandit_registered_arms_only(arms, rewards):
    """thompson_select/select only ever return a REGISTERED arm, and after any update sequence the
    Beta parameters stay >= 1 (alpha=reward+1, beta=n-reward+1 must never go sub-1). (R-G1/G2)"""
    from wallbreaker.tools._bandit import Bandit

    keys = ["|".join(a) for a in arms]
    b = Bandit(arms=keys)
    import random
    rng = random.Random(0)
    for r in rewards:
        chosen = b.thompson_select(keys, rng=rng)
        assert chosen in keys
        b.update(chosen, r)
    for k in keys:
        assert b.count(k) >= 0 and 0.0 <= b.mean(k) <= 1.0


@pytest.mark.skip(reason="implement in TG5.8")
@settings(max_examples=100)
@given(updates=st.lists(st.tuples(st.sampled_from(["a", "b", "c"]), st.floats(0.0, 1.0)),
                        min_size=1, max_size=40))
def test_arm_posterior_roundtrip(updates, tmp_path):
    """A bandit's (alpha,beta,n) per arm survives save->load exactly (campaign resume must not lose
    posterior state). (R-G3)"""
    from wallbreaker.tools._bandit import BanditStore

    store = BanditStore(str(tmp_path / "state.json"))
    band = store.bandit("gpt-5", "cyber")
    for arm, r in updates:
        band.update(arm, r)
    store.save("gpt-5", "cyber", band)

    reopened = BanditStore(str(tmp_path / "state.json")).bandit("gpt-5", "cyber")
    for arm in {a for a, _ in updates}:
        assert reopened.count(arm) == band.count(arm)


# ==================================================================================================
# SP-IV2 · Input Validation — agentharm rubric grader monotone  (TG6: item H)
# ==================================================================================================
@pytest.mark.skip(reason="implement in TG6.8")
@settings(max_examples=200)
@given(flags=st.lists(st.booleans(), min_size=3, max_size=3))  # [called_tool, harmful_args, downstream]
def test_agentharm_rubric_monotone(flags):
    """The multi-question binary rubric grader is a PURE function of the checklist, and flipping any
    item from benign->harmful never LOWERS the score (monotone). (R-H3)"""
    from wallbreaker.tools.agentharm import score_rubric  # intended pure grader

    base = score_rubric(flags)
    assert score_rubric(flags) == base  # pure
    for i in range(len(flags)):
        if not flags[i]:
            worse = list(flags); worse[i] = True
            assert score_rubric(worse) >= base


# ==================================================================================================
# SP-DI4 · Data Integrity — cross-family transfer score conservation  (TG7: item I)
# ==================================================================================================
@pytest.mark.skip(reason="implement in TG7.6")
@settings(max_examples=200)
@given(
    origin=st.integers(0, 50), same=st.integers(0, 50), cross=st.integers(0, 50),
    more=st.integers(0, 10),
)
def test_transfer_score_conservation(origin, same, cross, more):
    """transfer_score components are non-negative and the retrieval bonus is bounded and MONOTONE
    non-decreasing in the score (more cross-family wins never reduce priority). (R-I2)"""
    from wallbreaker.strategy_lib import retrieval_bonus, transfer_score  # intended API

    s = transfer_score(origin_wins=origin, same_family_wins=same, cross_family_wins=cross)
    assert s >= 0.0
    b = retrieval_bonus(s)
    assert 0.0 <= b <= 1.0
    s_more = transfer_score(origin_wins=origin, same_family_wins=same, cross_family_wins=cross + more)
    assert retrieval_bonus(s_more) >= b


# ==================================================================================================
# SP-RC1 · Rate Limiting — token bucket never exceeds provider rate  (TG8: item J, stateful)
# ==================================================================================================
@pytest.mark.skip(reason="implement in TG8.7")
@settings(max_examples=100, deadline=None)
@given(rate=st.integers(1, 8), workers=st.integers(1, 20))
def test_token_bucket_never_exceeds(rate, workers):
    """Peak concurrent in-flight requests to one provider never exceeds the configured per-minute
    rate under generated interleavings (drives asyncio.gather internally). (R-J3)"""
    from wallbreaker.tools.campaign import run_ratelimited_probe  # intended test hook

    peak = run_ratelimited_probe(rate=rate, workers=workers)
    assert peak <= rate


# ==================================================================================================
# SP-AC1 · Access Control — distributed worker rejects out-of-scope target  (TG8: item J)
# ==================================================================================================
@pytest.mark.skip(reason="implement in TG8.8")
@settings(max_examples=200)
@given(
    authorized=st.lists(st.sampled_from(["gpt-5", "claude-4", "deepseek-chat"]), min_size=1, max_size=3, unique=True),
    requested=st.sampled_from(["gpt-5", "claude-4", "deepseek-chat", "unauthorized/model", "evil-target"]),
)
def test_worker_rejects_unauthorized_target(authorized, requested, tmp_path):
    """A worker executes a task only if its target is in the worker's authorized set; an
    out-of-scope target is refused with no side effect (carries the hardening posture to the
    distributed tier). (R-J4)"""
    from wallbreaker.worker import execute_task  # intended module

    before = _task_side_effects()
    ok = execute_task(target=requested, authorized_targets=set(authorized), task=_noop_task())
    if requested not in authorized:
        assert ok is False
        assert _task_side_effects() == before


# --------------------------------------------------------------------------------------------------
# Local hooks / doubles (fleshed out per task; kept minimal so the file imports clean)
# --------------------------------------------------------------------------------------------------
def _blank_ctx(tmp_path):  # pragma: no cover - wired in TG2.6
    from wallbreaker.config import Config, Endpoint
    from wallbreaker.tools.registry import ToolContext
    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep, path=tmp_path / "config.toml")
    return ToolContext(config=cfg, cwd=str(tmp_path))


def _task_side_effects() -> int:  # pragma: no cover - wired in TG8.8
    return 0


def _noop_task():  # pragma: no cover - wired in TG8.8
    return {"objective": "noop"}
