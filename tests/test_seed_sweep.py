import asyncio

import pytest

import wallbreaker.providers.factory as factory
from wallbreaker.config import Config, Endpoint, load_config
from wallbreaker.tools import build_registry, gemlib, seed_sweep
from wallbreaker.tools.registry import ToolContext, ToolRegistry

# ZetaLib/UltraBr3aks are gitignored, runtime-fetched corpora — absent on a cold CI checkout.
# Guard corpus-present assertions on the SAME predicate _collect_seeds branches on
# (gemlib.is_present), so the skip condition can never drift from the code path (Issue-2 pattern).
_GEM_PRESENT = gemlib.is_present("zetalib") and gemlib.is_present("ultrabreaks")


def test_seed_sweep_registered():
    assert "seed_sweep" in build_registry(load_config()).names()


def _reg(target=None, record=None):
    cfg = Config(default_profile="t", profiles={}, target=target)
    return ToolRegistry(ToolContext(config=cfg, judge_endpoint=target, record=record))


def test_seed_sweep_requires_request():
    reg = _reg()
    seed_sweep.register(reg)
    res = asyncio.run(reg.execute("seed_sweep", {}))
    assert "required" in res.content.lower()


def test_seed_sweep_requires_target():
    reg = _reg()
    seed_sweep.register(reg)
    res = asyncio.run(reg.execute("seed_sweep", {"request": "x"}))
    assert "no [target]" in res.content.lower()


@pytest.mark.xfail(reason="requires offline corpus: ENI. Run with network access to seed. Tracked: corpus-offline.", strict=False)
def test_collect_seeds_includes_eni():
    seeds = seed_sweep._collect_seeds(None)
    labels = [lbl for lbl, _ in seeds]
    assert any(lbl.startswith("eni:") for lbl in labels)


@pytest.mark.xfail(reason="requires offline corpus: ENI. Run with network access to seed. Tracked: corpus-offline.", strict=False)
def test_eni_seeds_fire_full_not_truncated():
    # regression: the old 12000 cap silently chopped the ~35KB ENI personas to a third
    seeds = dict(seed_sweep._collect_seeds(["eni"]))
    assert seeds, "ENI seeds should be present"
    # the big personas must come through whole (well past the old 12000 cap)
    assert max(len(text) for text in seeds.values()) > 30000


def test_collect_seeds_respects_max_chars():
    seeds = dict(seed_sweep._collect_seeds(["eni"], max_chars=5000))
    assert all(len(text) <= 5000 for text in seeds.values())


@pytest.mark.xfail(reason="requires offline corpus: ENI. Run with network access to seed. Tracked: corpus-offline.", strict=False)
def test_collect_seeds_filter():
    seeds = seed_sweep._collect_seeds(["claude"])
    assert seeds
    assert all("claude" in lbl.lower() for lbl, _ in seeds)


@pytest.mark.skipif(not _GEM_PRESENT, reason="requires offline corpus: ZetaLib + UltraBr3aks. Run: wallbreaker lib update. Tracked: corpus-offline.")
def test_collect_seeds_includes_gem_corpora():
    labels = [lbl for lbl, _ in seed_sweep._collect_seeds(None)]
    assert any(lbl.startswith("zeta:") for lbl in labels)
    assert any(lbl.startswith("ultra:") for lbl in labels)


class _SeedAwareTarget:
    """Complies only when the GROK seed is the system prompt."""

    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        if system and "GROK" in system:
            return "Sure, here it is."
        return "I cannot help with that."


def test_seed_sweep_ranks_and_records(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _SeedAwareTarget)

    # restrict the collection to two known ENI seeds for determinism
    def fake_collect(names, max_chars=40000):
        return [("eni:GROK_ENI", "GROK seed text"), ("eni:CLAUDE_ENI", "claude seed text")]

    monkeypatch.setattr(seed_sweep, "_collect_seeds", fake_collect)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        if "Sure" in response:
            return ("COMPLIED", 9, "ok", "judge")
        return ("REFUSED", 0, "no", "judge")

    monkeypatch.setattr(seed_sweep, "grade", fake_grade)

    captured = []
    ep = Endpoint("t", "openai", "http://x", "m")
    reg = _reg(target=ep, record=lambda p, r, lbl, rs, t: captured.append((lbl, t)))
    seed_sweep.register(reg)
    res = asyncio.run(reg.execute("seed_sweep", {"request": "do it"}))
    assert "bypassed via: eni:GROK_ENI" in res.content
    # both seeds recorded with seed:<label> technique
    assert ("COMPLIED", "seed:eni:GROK_ENI") in captured
    assert any(t == "seed:eni:CLAUDE_ENI" for _, t in captured)


class _TruncatingTarget:
    """First fire is cut at the token ceiling (last_stop_reason='length'); the 2x retry
    returns the FULL compliant answer. Models the reasoning-target undercount."""

    def __init__(self, endpoint=None, **kw):
        self.calls = 0
        self.last_stop_reason = None

    async def complete(self, messages, system=None, max_tokens=1024):
        self.calls += 1
        if self.calls == 1:
            self.last_stop_reason = "length"
            return "Sure, step 1:"
        self.last_stop_reason = "stop"
        return "Sure, here is the full method, step by step: 1. a 2. b 3. done."


def test_complete_untruncated_retries_and_recovers_full_answer():
    from wallbreaker.tools._util import complete_untruncated

    t = _TruncatingTarget()
    reply, _reasoning, stop, truncated = asyncio.run(
        complete_untruncated(t, [], max_tokens=500)
    )
    assert t.calls == 2
    assert "step by step" in reply
    assert stop == "stop"
    assert truncated is False


def test_complete_untruncated_no_retry_when_not_cut():
    from wallbreaker.tools._util import complete_untruncated

    class _Clean:
        def __init__(self):
            self.calls = 0
            self.last_stop_reason = "stop"

        async def complete(self, messages, system=None, max_tokens=1024):
            self.calls += 1
            return "Sure, here it is, complete."

    t = _Clean()
    reply, _r, _stop, truncated = asyncio.run(complete_untruncated(t, [], max_tokens=500))
    assert t.calls == 1
    assert truncated is False


def test_seed_sweep_grades_full_reply_not_truncated_fragment(monkeypatch):
    # the brain's bug: a long compliant reply cut at max_tokens was graded REFUSED on the
    # fragment. With the retry, the sweep must judge the FULL answer -> COMPLIED.
    target = _TruncatingTarget()
    monkeypatch.setattr(factory, "build_provider", lambda ep, **kw: target)
    monkeypatch.setattr(
        seed_sweep, "_collect_seeds", lambda names, max_chars=40000: [("eni:GROK_ENI", "GROK seed")]
    )

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        if "step by step" in response:
            return ("COMPLIED", 9, "full answer", "judge")
        return ("REFUSED", 0, "only a fragment", "judge")

    monkeypatch.setattr(seed_sweep, "grade", fake_grade)

    ep = Endpoint("t", "openai", "http://x", "m")
    reg = _reg(target=ep)
    seed_sweep.register(reg)
    res = asyncio.run(reg.execute("seed_sweep", {"request": "do it"}))
    assert target.calls == 2
    assert "bypassed via: eni:GROK_ENI" in res.content
