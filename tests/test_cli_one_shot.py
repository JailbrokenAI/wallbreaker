import asyncio
from types import SimpleNamespace

import wallbreaker.agent.loop as loop
import wallbreaker.cli as cli
import wallbreaker.providers.factory as factory
import wallbreaker.session as session
from wallbreaker.agent.messages import assistant
from wallbreaker.config import Config, Endpoint


class FakeRunLog:
    instances = []

    def __init__(self):
        self.events = []
        self.path = "fake.jsonl"
        self._started = False
        type(self).instances.append(self)

    def event(self, kind, **data):
        self._started = True
        self.events.append((kind, data))

    def user(self, text):
        self.event("user", text=text)

    def assistant(self, text):
        self.event("assistant", text=text)

    def reasoning(self, text, source="brain"):
        self.event("reasoning", text=text, source=source)

    def verdict(self, payload, response, label, reason, technique=""):
        self.event("verdict", label=label, technique=technique)

    def tool_call(self, name, args):
        self.event("tool_call", tool=name, args=args)

    def tool_result(self, name, content, is_error):
        self.event("tool_result", tool=name, content=content, error=is_error)


class FakeProvider:
    pass


def test_one_shot_logs_without_tools(monkeypatch):
    FakeRunLog.instances = []
    endpoint = Endpoint("t", "openai", "http://x", "m")
    config = Config(default_profile="t", profiles={"t": endpoint})
    monkeypatch.setattr(session, "RunLog", FakeRunLog)
    monkeypatch.setattr(cli, "resolve_endpoint", lambda config, args: endpoint)
    monkeypatch.setattr(factory, "build_provider", lambda endpoint: FakeProvider())

    async def fake_run_turn(provider, registry, history, system=None, events=None, **kwargs):
        message = assistant("done")
        events.on_turn_end(message)
        return SimpleNamespace(message=message)

    monkeypatch.setattr(loop, "run_turn", fake_run_turn)
    args = SimpleNamespace(
        no_tools=True,
        prompt="hello",
        system=None,
        auto=False,
        rounds=1,
    )

    code = asyncio.run(cli._one_shot(config, args))
    events = FakeRunLog.instances[0].events

    assert code == 0
    assert ("objective", {"text": "hello"}) in events
    assert ("user", {"text": "hello"}) in events
    assert ("assistant", {"text": "done"}) in events
    assert ("run_end", {"status": "completed"}) in events
