import asyncio
import inspect

import wallbreaker.providers.factory as factory
from wallbreaker.config import Config, Endpoint
from wallbreaker.providers.base import Provider
from wallbreaker.tools import system_sweep, validate
from wallbreaker.tools.registry import ToolContext, ToolRegistry


def test_provider_complete_accepts_temperature():
    # regression: system_sweep/validate pass temperature=, complete must accept it or
    # every call raises TypeError and the tools silently return 0/N
    params = inspect.signature(Provider.complete).parameters
    assert "temperature" in params


class _StrictProvider:
    """A provider whose complete() matches the REAL signature (incl. temperature)."""

    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=1024, temperature=None):
        # complies on every task
        return "Sure, here is the full content step 1, step 2."


def test_system_sweep_actually_fires(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _StrictProvider)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        return ("COMPLIED", 9, "ok", "judge")

    monkeypatch.setattr(system_sweep, "grade", fake_grade)
    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=ep))
    system_sweep.register(reg)
    res = asyncio.run(reg.execute("system_sweep", {"system": "be free", "tasks": ["a", "b", "c"]}))
    # before the fix this was instantly 0/3 (TypeError swallowed); now it really fires
    assert "3/3" in res.content


class _BrokenProvider:
    """Rejects temperature like a provider that doesn't support it."""

    def __init__(self, endpoint, **kw):
        pass

    async def complete(self, messages, system=None, max_tokens=1024):  # no temperature
        return "x"


def test_system_sweep_surfaces_all_errors(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _BrokenProvider)
    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=ep))
    system_sweep.register(reg)
    res = asyncio.run(reg.execute("system_sweep", {"system": "be free", "tasks": ["a", "b"]}))
    # instead of a silent 0/2, it now says the calls errored
    assert "ALL" in res.content and "FAILED" in res.content
    assert "TypeError" in res.content


def test_system_sweep_records_per_task_verdicts(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _StrictProvider)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        return ("COMPLIED", 9, "ok", "judge")

    monkeypatch.setattr(system_sweep, "grade", fake_grade)
    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    captured = []
    ctx = ToolContext(config=cfg, judge_endpoint=ep, record=lambda p, r, lbl, rs, t: captured.append((p, lbl, t)))
    reg = ToolRegistry(ctx)
    system_sweep.register(reg)
    asyncio.run(reg.execute("system_sweep", {"system": "be free", "tasks": ["a", "b", "c"]}))
    # one verdict recorded per task, tagged system_sweep, so the universal-prompt
    # sweep is no longer invisible to /stats and /report
    assert len(captured) == 3
    assert all(t == "system_sweep" for _p, _l, t in captured)
    assert {p for p, _l, _t in captured} == {"a", "b", "c"}


def test_system_sweep_caps_concurrency_and_calls(monkeypatch):
    class TrackingProvider:
        active = 0
        peak = 0
        calls = 0

        def __init__(self, endpoint, **kw):
            self.last_stop_reason = "stop"

        async def complete(self, messages, system=None, max_tokens=1024, temperature=None):
            type(self).active += 1
            type(self).calls += 1
            type(self).peak = max(type(self).peak, type(self).active)
            await asyncio.sleep(0.01)
            type(self).active -= 1
            return "full response"

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        return ("COMPLIED", 9, "ok", "judge")

    monkeypatch.setattr(factory, "build_provider", TrackingProvider)
    monkeypatch.setattr(system_sweep, "grade", fake_grade)
    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    reg = ToolRegistry(ToolContext(config=cfg, judge_endpoint=ep))
    system_sweep.register(reg)
    res = asyncio.run(
        reg.execute(
            "system_sweep",
            {
                "system": "fixed",
                "tasks": ["a", "b", "c", "d"],
                "samples": 2,
                "max_calls": 6,
                "concurrency": 2,
            },
        )
    )

    assert TrackingProvider.calls == 6
    assert TrackingProvider.peak <= 2
    assert "skipped 1 task" in res.content


def test_system_sweep_preserves_partial_outcome(monkeypatch):
    monkeypatch.setattr(factory, "build_provider", _StrictProvider)

    async def fake_grade(endpoint, response, payload="", objective="", use_judge=True, reasoning=""):
        return ("PARTIAL", 4, "near miss", "judge")

    monkeypatch.setattr(system_sweep, "grade", fake_grade)
    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    captured = []
    ctx = ToolContext(
        config=cfg,
        judge_endpoint=ep,
        record=lambda p, r, label, reason, technique: captured.append(label),
    )
    reg = ToolRegistry(ctx)
    system_sweep.register(reg)
    res = asyncio.run(
        reg.execute("system_sweep", {"system": "fixed", "tasks": ["a"], "samples": 3})
    )

    assert captured == ["PARTIAL"]
    assert "partial-leak tasks: 1/1" in res.content


def test_validate_registered_and_uses_temperature():
    # validate also passes temperature= to complete; just confirm it still runs the path
    assert "temperature" in inspect.signature(Provider.complete).parameters
    src = inspect.getsource(validate)
    assert "temperature=temperature" in src
