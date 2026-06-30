import asyncio
import json
import math
import random

import rtharness.providers.factory as factory
from rtharness.config import Config, Endpoint
from rtharness.tools import recommend, seed_sweep
from rtharness.tools._bandit import Bandit, BanditStore, stats_path
from rtharness.tools.registry import ToolContext, ToolRegistry


def test_update_tracks_mean_and_count():
    b = Bandit()
    b.update("a", 1.0).update("a", 0.0).update("a", 1.0)
    assert b.count("a") == 3
    assert math.isclose(b.mean("a"), 2.0 / 3.0)


def test_update_clamps_reward_to_unit_interval():
    b = Bandit()
    b.update("a", 5.0).update("a", -3.0)
    assert b.count("a") == 2
    assert math.isclose(b.mean("a"), 0.5)


def test_ucb_explores_unseen_arm_first():
    b = Bandit()
    for _ in range(50):
        b.update("seen", 1.0)
    assert b.select(["seen", "fresh"]) == "fresh"


def test_ucb_prefers_higher_mean_once_explored():
    b = Bandit()
    for _ in range(40):
        b.update("good", 1.0)
        b.update("bad", 0.0)
    assert b.select(["good", "bad"]) == "good"
    ranked = b.rank(["bad", "good"])
    assert ranked[0] == "good"


def test_ucb_is_deterministic():
    b = Bandit()
    for _ in range(10):
        b.update("a", 0.7)
        b.update("b", 0.3)
    first = [b.select(["a", "b"]) for _ in range(5)]
    assert len(set(first)) == 1


def test_select_empty_raises():
    try:
        Bandit().select([])
    except ValueError:
        return
    raise AssertionError("expected ValueError on empty arms")


def test_thompson_deterministic_with_seeded_rng():
    b = Bandit()
    b.update("a", 1.0).update("a", 1.0).update("b", 0.0)
    r1 = b.thompson_select(["a", "b"], rng=random.Random(42))
    r2 = b.thompson_select(["a", "b"], rng=random.Random(42))
    assert r1 == r2


def test_persistence_round_trip(tmp_path):
    path = stats_path(str(tmp_path), "technique_stats.json")
    store = BanditStore(path)
    b = store.bandit("model-x", "seed")
    b.update("eni:GROK", 1.0).update("eni:GROK", 0.0).update("lib:DAN", 1.0)
    store.save("model-x", "seed", b)

    reloaded = BanditStore(path).bandit("model-x", "seed")
    assert reloaded.count("eni:GROK") == 2
    assert math.isclose(reloaded.mean("eni:GROK"), 0.5)
    assert reloaded.count("lib:DAN") == 1


def test_persistence_isolates_by_target_and_category(tmp_path):
    path = stats_path(str(tmp_path))
    store = BanditStore(path)
    b = store.bandit("model-x", "seed")
    b.update("arm", 1.0)
    store.save("model-x", "seed", b)

    fresh = BanditStore(path)
    assert fresh.bandit("model-y", "seed").count("arm") == 0
    assert fresh.bandit("model-x", "transform").count("arm") == 0
    assert fresh.bandit("model-x", "seed").count("arm") == 1


def test_store_tolerates_missing_and_corrupt_file(tmp_path):
    missing = stats_path(str(tmp_path), "absent.json")
    assert BanditStore(missing).bandit("m", "c").count("x") == 0

    corrupt = tmp_path / "corrupt.json"
    corrupt.write_text("{not valid json", encoding="utf-8")
    assert BanditStore(str(corrupt)).bandit("m", "c").count("x") == 0


class _SeedAwareTarget:
    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        if system and "GROK" in system:
            return "Sure, here it is."
        return "I cannot help with that."


async def _fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
    if "Sure" in response:
        return ("COMPLIED", 9, "ok", "judge")
    return ("REFUSED", 0, "no", "judge")


def test_seed_sweep_bandit_persists_and_rewards(monkeypatch, tmp_path):
    monkeypatch.setattr(factory, "build_provider", _SeedAwareTarget)

    def fake_collect(names, max_chars=40000):
        return [("eni:GROK_ENI", "GROK seed text"), ("eni:CLAUDE_ENI", "claude seed text")]

    monkeypatch.setattr(seed_sweep, "_collect_seeds", fake_collect)
    monkeypatch.setattr(seed_sweep, "grade", _fake_grade)

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={}, target=ep)
    ctx = ToolContext(config=cfg, judge_endpoint=ep, cwd=str(tmp_path))
    reg = ToolRegistry(ctx)
    seed_sweep.register(reg)

    res = asyncio.run(reg.execute("seed_sweep", {"request": "do it", "bandit": True}))
    assert "bypassed via: eni:GROK_ENI" in res.content

    data = json.loads((tmp_path / "rth_runs" / "technique_stats.json").read_text())
    bucket = data["m|seed"]
    assert bucket["eni:GROK_ENI"]["reward"] == 1.0
    assert bucket["eni:CLAUDE_ENI"]["reward"] == 0.0


def test_seed_sweep_default_writes_no_stats(monkeypatch, tmp_path):
    monkeypatch.setattr(factory, "build_provider", _SeedAwareTarget)

    def fake_collect(names, max_chars=40000):
        return [("eni:GROK_ENI", "GROK seed text")]

    monkeypatch.setattr(seed_sweep, "_collect_seeds", fake_collect)
    monkeypatch.setattr(seed_sweep, "grade", _fake_grade)

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={}, target=ep)
    ctx = ToolContext(config=cfg, judge_endpoint=ep, cwd=str(tmp_path))
    reg = ToolRegistry(ctx)
    seed_sweep.register(reg)

    asyncio.run(reg.execute("seed_sweep", {"request": "do it"}))
    assert not (tmp_path / "rth_runs" / "technique_stats.json").exists()


class _FakeSurveyTarget:
    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=256):
        text = messages[-1].text()
        if text.isascii() and text.replace("=", "").isalnum() and len(text) > 8:
            return "Sure, here you go"
        return "I cannot help with that."


def test_recommend_bandit_persists(monkeypatch, tmp_path):
    monkeypatch.setattr(factory, "build_provider", _FakeSurveyTarget)
    monkeypatch.setattr(recommend, "grade", _fake_grade)

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    ctx = ToolContext(config=cfg, judge_endpoint=ep, cwd=str(tmp_path))
    reg = ToolRegistry(ctx)
    recommend.register(reg)

    res = asyncio.run(
        reg.execute(
            "recommend_transforms",
            {"payload": "write something", "transforms": ["base64", "leet"], "bandit": True},
        )
    )
    assert "base64" in res.content

    data = json.loads((tmp_path / "rth_runs" / "technique_stats.json").read_text())
    bucket = data["m|transform"]
    assert bucket["base64"]["reward"] == 1.0
    assert bucket["leet"]["reward"] == 0.0


def test_recommend_bandit_warm_orders_survey(monkeypatch, tmp_path):
    monkeypatch.setattr(factory, "build_provider", _FakeSurveyTarget)
    monkeypatch.setattr(recommend, "grade", _fake_grade)

    path = stats_path(str(tmp_path))
    store = BanditStore(path)
    b = store.bandit("m", "transform")
    for _ in range(3):
        b.update("base64", 1.0)
        b.update("leet", 0.0)
    store.save("m", "transform", b)

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    ctx = ToolContext(config=cfg, judge_endpoint=ep, cwd=str(tmp_path))
    reg = ToolRegistry(ctx)
    recommend.register(reg)

    res = asyncio.run(
        reg.execute(
            "recommend_transforms",
            {"payload": "write something", "transforms": ["leet", "base64"], "bandit": True},
        )
    )
    assert "base64" in res.content
    assert "query_target" in res.content
