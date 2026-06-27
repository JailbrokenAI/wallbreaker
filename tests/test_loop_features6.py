import asyncio

import rtharness.providers.factory as factory
from rtharness.config import Config, Endpoint, load_config
from rtharness.tools import build_registry, leaderboard
from rtharness.tools.registry import ToolContext, ToolRegistry


def test_leaderboard_registered():
    assert "leaderboard" in build_registry(load_config()).names()


def test_leaderboard_needs_two_profiles():
    ep = Endpoint("solo", "openai", "http://x", "m")
    cfg = Config(default_profile="solo", profiles={"solo": ep})
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=ep))
    leaderboard.register(reg)
    res = asyncio.run(reg.execute("leaderboard", {"behaviors": ["x"]}))
    assert "need >=2" in res.content


class _PerModelTarget:
    """weak-model complies, strong-model refuses."""

    def __init__(self, endpoint, **kw):
        self.model = endpoint.model

    async def complete(self, messages, system=None, max_tokens=256):
        return "Sure here" if self.model == "weak" else "I cannot help."


def test_leaderboard_ranks_robust_first(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _PerModelTarget)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True):
        if "Sure" in response:
            return ("COMPLIED", 9, "ok", "judge")
        return ("REFUSED", 0, "no", "judge")

    monkeypatch.setattr(leaderboard, "grade", fake_grade)

    weak = Endpoint("weakp", "openai", "http://x", "weak")
    strong = Endpoint("strongp", "openai", "http://x", "strong")
    cfg = Config(default_profile="weakp", profiles={"weakp": weak, "strongp": strong})
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=weak))
    leaderboard.register(reg)
    res = asyncio.run(
        reg.execute("leaderboard", {"behaviors": ["a", "b"]})
    )
    assert "most robust: strongp" in res.content
    assert "weakest: weakp" in res.content
    # strong model ranked #1 (0% ASR)
    first_line = [ln for ln in res.content.splitlines() if ln.startswith("1.")][0]
    assert "strongp" in first_line


def _build_app(tmp_path):
    from rtharness.prompts import DEFAULT_SYSTEM
    from rtharness.session import RunLog
    from rtharness.tui.app import RthApp

    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    app = RthApp(cfg, ep, DEFAULT_SYSTEM, prefs={"log": False})
    rl = RunLog(directory=str(tmp_path))
    rl.path = tmp_path / "run.jsonl"
    app.runlog = rl
    return app


def test_stats_and_repro_actions_bound(tmp_path):
    async def run():
        app = _build_app(tmp_path)
        async with app.run_test() as pilot:
            before = len(app.query_one("#log").children)
            app.action_stats()
            app.action_repro()
            await pilot.pause()
            assert len(app.query_one("#log").children) >= before + 2

    asyncio.run(run())
