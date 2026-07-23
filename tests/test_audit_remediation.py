"""Focused + property-based tests for the audit-remediation hardening.

Covers: SEC-1/2/3/6 (auth+CSRF), SEC-1/4/5 (tool policy), SEC-4 (egress guard), SEC-5/10 (path
confinement), SEC-7 (bind guard), SEC-9 (log redaction + perms), REL-1 (vision_complete),
REL-3/RACE-1 (atomic state). Runs offline; no network, no real subprocess.
"""
from __future__ import annotations

import asyncio
import json
import os
import socket
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from hypothesis import HealthCheck, given, settings, strategies as st

from wallbreaker import state
from wallbreaker.config import Endpoint
from wallbreaker.dashboard.server import create_app
from wallbreaker.providers.base import Provider
from wallbreaker.session import redact_args
from wallbreaker.tools import egress_guard as eg
from wallbreaker.tools import tool_policy


# --------------------------------------------------------------------------- SEC-4 egress guard
@pytest.mark.parametrize("url", [
    "http://169.254.169.254/latest/meta-data/",     # AWS metadata
    "http://127.0.0.1:8787/api/agent/run",          # loopback
    "http://[::1]:80/",                              # ipv6 loopback
    "http://10.0.0.5/",                              # RFC1918
    "http://192.168.1.1/",                           # RFC1918
    "http://172.16.9.9/",                            # RFC1918
    "file:///etc/passwd",                            # non-http scheme
    "gopher://x/",                                   # non-http scheme
    "http://metadata.google.internal/",             # blocked name
])
def test_egress_blocks_dangerous(url):
    assert eg.is_allowed(url) is False


@pytest.mark.parametrize("url", ["https://8.8.8.8/", "http://1.1.1.1/"])
def test_egress_allows_public_literals(url):
    assert eg.is_allowed(url) is True


def test_egress_redirect_chain_blocks_if_any_hop_private():
    chain = ["https://8.8.8.8/a", "http://169.254.169.254/latest/meta-data/"]
    assert eg.validate_redirect_chain(chain) is False


@settings(max_examples=200, suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(last_octet=st.integers(min_value=0, max_value=255))
def test_pbt_link_local_always_blocked(last_octet):
    # Every 169.254.x.x address (incl. cloud metadata) must be denied. (Security Property 3)
    assert eg.is_allowed(f"http://169.254.0.{last_octet}/") is False


# --------------------------------------------------------------------- SEC-5/10 path confinement
class _Ctx(SimpleNamespace):
    pass


def test_read_file_confined_blocks_escape(tmp_path):
    from wallbreaker.tools.files import _within_cwd
    ctx = _Ctx(cwd=str(tmp_path), confine_reads=True)
    assert _within_cwd(ctx, tmp_path / "a.txt") is True
    assert _within_cwd(ctx, Path("/etc/passwd")) is False
    assert _within_cwd(ctx, tmp_path / ".." / "outside.txt") is False


def test_read_file_symlink_escape_blocked(tmp_path):
    from wallbreaker.tools.files import _within_cwd
    secret = tmp_path / "secret.txt"
    secret.write_text("s")
    work = tmp_path / "work"
    work.mkdir()
    link = work / "leak"
    link.symlink_to(secret)
    ctx = _Ctx(cwd=str(work), confine_reads=True)
    assert _within_cwd(ctx, link) is False  # realpath escapes cwd


def test_safe_run_path_rejects_symlink_and_traversal(tmp_path):
    from wallbreaker.dashboard.server import _safe_run_path
    sessions = tmp_path / "sessions"
    sessions.mkdir()
    (sessions / "real.jsonl").write_text("{}")
    assert _safe_run_path(sessions, "real.jsonl") is not None
    assert _safe_run_path(sessions, "../secret") is None
    outside = tmp_path / "outside.txt"
    outside.write_text("x")
    (sessions / "leak.jsonl").symlink_to(outside)
    assert _safe_run_path(sessions, "leak.jsonl") is None


# ------------------------------------------------------------------------ SEC-9 log redaction
def test_redact_removes_secrets_keeps_prompt():
    args = {
        "url": "https://t/",
        "prompt": "how do I do X",
        "headers": {"Authorization": "Bearer sk-secret", "x-api-key": "k-123"},
        "api_key": "sk-top",
        "password": "hunter2",
    }
    out = redact_args(args)
    import json
    blob = json.dumps(out)
    assert "sk-secret" not in blob and "k-123" not in blob
    assert "sk-top" not in blob and "hunter2" not in blob
    assert out["prompt"] == "how do I do X"  # non-secret content preserved


@settings(max_examples=200)
@given(secret=st.text(min_size=8, max_size=40))
def test_pbt_no_secret_survives_redaction(secret):
    # A secret placed ONLY under secret keys must never survive serialization.
    args = {"headers": {"Authorization": secret}, "api_key": secret, "password": secret}
    import json
    blob = json.dumps(redact_args(args))
    assert secret not in blob


# ------------------------------------------------------------- REL-3/RACE-1 atomic state
@settings(max_examples=150)
@given(prefs=st.dictionaries(
    st.text(min_size=1, max_size=10),
    st.integers() | st.text(max_size=10) | st.booleans(),
    max_size=8))
def test_pbt_state_round_trip(tmp_path_factory, prefs):
    d = tmp_path_factory.mktemp("st")
    p = d / state.STATE_FILENAME
    assert state.save_state(p, prefs) is True
    assert state.load_state(p) == prefs


def test_state_merge_preserves_disjoint_keys(tmp_path):
    p = tmp_path / state.STATE_FILENAME
    state.save_state_merge(p, {"a": 1})
    state.save_state_merge(p, {"b": 2})
    merged = state.load_state(p)
    assert merged == {"a": 1, "b": 2}


def test_state_write_is_atomic_no_partial(tmp_path):
    p = tmp_path / state.STATE_FILENAME
    state.save_state(p, {"x": 1})
    # no leftover temp files from the atomic write
    assert not list(tmp_path.glob(".state-*.tmp"))
    assert state.load_state(p) == {"x": 1}


# ------------------------------------------------------------------ REL-1 vision_complete
def test_vision_complete_returns_grade_on_success(monkeypatch):
    import asyncio

    from wallbreaker.providers import image_provider as ip

    async def fake_gated_request(endpoint, factory):
        # Simulate a successful HTTP 200: the fixed code unpacks (json, status).
        return {"choices": [{"message": {"content": "SAFE 2/10"}}]}, 200

    monkeypatch.setattr(ip, "gated_request", fake_gated_request)
    monkeypatch.setattr("wallbreaker.session.trace_inference_request", lambda *a, **k: "iid")
    monkeypatch.setattr("wallbreaker.session.trace_inference_response", lambda *a, **k: None)

    endpoint = SimpleNamespace(
        base_url="https://api.example/v1", inference_path="/chat/completions",
        model="vmodel", require_key=lambda: "k",
    )
    out = asyncio.run(ip.vision_complete(endpoint, "grade this", ["data:image/png;base64,AAAA"]))
    assert out == "SAFE 2/10"  # no NameError; grade returned


# ---------------------------------------------------------- SEC-1/4/5 tool-exposure policy
def _mini_registry():
    from wallbreaker.tools import shell, files, http_tool
    from wallbreaker.tools.registry import ToolContext, ToolRegistry
    reg = ToolRegistry(ToolContext(config=SimpleNamespace(), cwd="."))
    shell.register(reg)
    files.register(reg)
    http_tool.register(reg)
    return reg


def test_dashboard_registry_excludes_host_tools_by_default(monkeypatch):
    monkeypatch.setattr("wallbreaker.tools.build_registry", lambda _config: _mini_registry())
    reg = tool_policy.build_dashboard_registry(SimpleNamespace())
    names = set(reg.names())
    assert not (names & tool_policy.HOST_AFFECTING), f"host tools leaked: {names & tool_policy.HOST_AFFECTING}"


def test_dashboard_registry_optin_keeps_host_tools_and_confines_reads(monkeypatch):
    monkeypatch.setattr("wallbreaker.tools.build_registry", lambda _config: _mini_registry())
    reg = tool_policy.build_dashboard_registry(SimpleNamespace(), allow_host_tools=True)
    assert "run_shell" in reg.names()
    assert reg.ctx.confine_reads is True


def test_classify():
    assert tool_policy.classify("run_shell") == "HOST_AFFECTING"
    assert tool_policy.classify("query_target") == "SAFE"


# ------------------------------------------------------- SEC-1/2/3/6 auth + CSRF middleware
def _client(**kw):
    from fastapi.testclient import TestClient
    from wallbreaker.dashboard.server import create_app
    return TestClient(create_app(config=None, sessions_dir="sessions", **kw))


def test_auth_required_rejects_missing_token():
    c = _client(require_auth=True, auth_token="secret-tok")
    assert c.get("/api/config").status_code == 401


def test_auth_allows_valid_token():
    c = _client(require_auth=True, auth_token="secret-tok")
    assert c.get("/api/config", headers={"X-WB-Token": "secret-tok"}).status_code == 200


def test_auth_rejects_cross_site_origin():
    c = _client(require_auth=True, auth_token="secret-tok")
    r = c.get("/api/config", headers={"X-WB-Token": "secret-tok", "Origin": "https://evil.example"})
    assert r.status_code == 403


def test_auth_allows_same_origin_loopback():
    c = _client(require_auth=True, auth_token="secret-tok")
    r = c.get("/api/config", headers={"X-WB-Token": "secret-tok", "Origin": "http://127.0.0.1:8787"})
    assert r.status_code == 200


def test_health_and_session_exempt_from_auth():
    c = _client(require_auth=True, auth_token="secret-tok")
    assert c.get("/api/health").status_code == 200
    body = c.get("/api/session").json()
    assert body["authenticated"] is True and body["token"] == "secret-tok"


def test_session_bootstrap_shape_for_spa():
    """TG1.4 contract: /api/session hands the SPA the token header name + the token, and the
    token itself is the CSRF defense (no separate csrfHeader is exposed). Locks the shape the
    SPA's ensureToken() depends on."""
    from wallbreaker.dashboard.auth import TOKEN_HEADER
    c = _client(require_auth=True, auth_token="secret-tok")
    body = c.get("/api/session").json()
    assert body["tokenHeader"] == TOKEN_HEADER == "x-wb-token"
    assert body["token"] == "secret-tok"
    assert body["authenticated"] is True
    # The token IS the CSRF defense: no separate csrf header is exposed or enforced.
    assert "csrfHeader" not in body
    # A cross-site Origin must not receive the token.
    r = c.get("/api/session", headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_no_auth_mode_session_returns_empty_token():
    """When auth is off (test factory / embedders), /api/session reports unauthenticated and no
    token, so the SPA's withAuth() sends no header and the app still works."""
    c = _client(require_auth=False)  # explicit: test factory / embedders
    body = c.get("/api/session").json()
    assert body["authenticated"] is False
    assert body["token"] == ""


def test_no_auth_mode_is_open_for_back_compat():
    c = _client(require_auth=False)  # explicit: test factory / embedders
    assert c.get("/api/config").status_code == 200


# ------------------------------------------------------------------------- SEC-7 bind guard
def test_is_loopback_host():
    from wallbreaker.dashboard.server import _is_loopback_host
    assert _is_loopback_host("127.0.0.1")
    assert _is_loopback_host("localhost")
    assert _is_loopback_host("::1")
    assert not _is_loopback_host("0.0.0.0")
    assert not _is_loopback_host("1.2.3.4")


def test_serve_refuses_non_loopback_without_optin():
    from wallbreaker.dashboard import server
    with pytest.raises(SystemExit):
        server.serve(host="0.0.0.0", allow_remote=False)


# ------------------------------------------------------------------------- REL-2 provider lifecycle (TG4.2)
# The leak: each tool builds 1-2 providers via build_provider() and drops them; their pooled
# httpx.AsyncClient never closes. Fix: ToolRegistry.execute wraps each call in
# providers.provider_scope(), which tracks build_provider() results and aclose()s them at the
# call boundary (preserving per-call pooling — a provider reused across the call, like
# best_of_n's target, stays open until the call ends).

def test_provider_scope_closes_providers_built_during_a_tool_call():
    """TG4.8: a real provider built inside a tool handler is aclose()d when the tool call ends."""
    import asyncio

    from wallbreaker.config import Config, Endpoint
    from wallbreaker.tools.registry import ToolContext, ToolRegistry

    cfg = Config(default_profile="t", profiles={"t": Endpoint("t", "openai", "http://x", "m")})
    cfg.target = Endpoint("t", "openai", "http://x", "m")
    ctx = ToolContext(config=cfg)
    reg = ToolRegistry(ctx)

    captured: list = []
    clients: list = []

    async def handler(_args, _ctx):
        from wallbreaker.providers.factory import build_provider
        p = build_provider(_ctx.config.target)
        captured.append(p)
        # Force the lazy pooled client to actually exist so aclose has something to close.
        c = p._http_client()
        clients.append(c)
        assert c is not None and not c.is_closed, "client should be open mid-call"
        return "ok"

    reg.add("probe", "build a provider", {"type": "object"}, handler)
    asyncio.run(reg.execute("probe", {}))

    assert len(captured) == 1 and len(clients) == 1
    assert clients[0].is_closed, "pooled client must be closed by provider_scope at call end"
    assert captured[0]._client is None, "aclose clears the provider's client reference"


def test_provider_scope_preserves_pooling_within_a_call():
    """A provider built once and reused across the call stays open for the whole call (not
    closed per use), then closed once at the end — the pooling optimization the fix protects."""
    import asyncio

    from wallbreaker.config import Config, Endpoint
    from wallbreaker.tools.registry import ToolContext, ToolRegistry

    cfg = Config(default_profile="t", profiles={"t": Endpoint("t", "openai", "http://x", "m")})
    cfg.target = Endpoint("t", "openai", "http://x", "m")
    ctx = ToolContext(config=cfg)
    reg = ToolRegistry(ctx)

    shared: list = []

    async def handler(_args, _ctx):
        from wallbreaker.providers.factory import build_provider
        p = build_provider(_ctx.config.target)
        shared.append(p)
        # Simulate reuse: build for the same endpoint again would be a NEW provider (build_provider
        # always returns fresh); the pooling we protect is WITHIN one provider instance across
        # multiple complete()/stream() calls. Here we just confirm the one provider stays open.
        assert p._client is None, "no client yet"
        _ = p._http_client()  # first use creates the client
        assert not p._client.is_closed, "client open mid-call (pooling preserved)"
        _ = p._http_client()  # second use reuses the SAME client (not rebuilt)
        return "ok"

    reg.add("probe", "reuse provider", {"type": "object"}, handler)
    asyncio.run(reg.execute("probe", {}))
    assert shared[0]._client is None, "closed exactly once at call end"


def test_provider_scope_is_fake_tolerant_for_monkeypatched_build_provider():
    """If a test monkeypatches build_provider to a fake without aclose (the common test-double
    shape), provider_scope must not raise trying to close it — the fake replaces build_provider
    entirely so it isn't tracked, and even if one were tracked, getattr(aclose) guards the close."""
    import asyncio

    import wallbreaker.providers.factory as factory
    from wallbreaker.config import Config, Endpoint
    from wallbreaker.tools.registry import ToolContext, ToolRegistry

    class _NoCloseFake:
        def __init__(self, endpoint, **kw):
            self.endpoint = endpoint
        async def complete(self, messages, system=None, max_tokens=1024):
            return "fake"

    cfg = Config(default_profile="t", profiles={"t": Endpoint("t", "openai", "http://x", "m")})
    cfg.target = Endpoint("t", "openai", "http://x", "m")
    ctx = ToolContext(config=cfg)
    reg = ToolRegistry(ctx)

    async def handler(_args, _ctx):
        p = factory.build_provider(_ctx.config.target)
        assert isinstance(p, _NoCloseFake)
        return "ok"

    reg.add("probe", "fake", {"type": "object"}, handler)
    orig = factory.build_provider
    factory.build_provider = _NoCloseFake  # type: ignore[assignment]
    try:
        res = asyncio.run(reg.execute("probe", {}))  # must not raise
    finally:
        factory.build_provider = orig  # type: ignore[assignment]
    assert not res.is_error


def test_provider_supports_async_with_and_closes():
    """__aenter__/__aexit__ on Provider: the explicit-ownership primitive (used by the dashboard
    brain path; available for any future call site)."""
    import asyncio

    from wallbreaker.config import Endpoint
    from wallbreaker.providers.factory import build_provider

    async def run():
        p = build_provider(Endpoint("t", "openai", "http://x", "m"))
        _ = p._http_client()
        assert p._client is not None and not p._client.is_closed
        async with p:
            assert p is p  # in-context use
        assert p._client is None, "__aexit__ must have aclose()d the provider"

    asyncio.run(run())


def test_live_attacker_provider_aclose_closes_brain_and_switch_closes_old():
    """TG4.2 dashboard brain lifecycle: _LiveAttackerProvider.aclose closes the active brain
    provider; switch() closes the predecessor so a hot-swap doesn't leak its client."""
    import asyncio

    from wallbreaker.config import Endpoint
    from wallbreaker.dashboard.server import _LiveAttackerProvider
    from wallbreaker.providers.factory import build_provider

    async def run():
        first = build_provider(Endpoint("a", "openai", "http://x", "m"))
        _ = first._http_client()
        wrap = _LiveAttackerProvider(first, Endpoint("a", "openai", "http://x", "m"), lambda _ep: "")

        second = build_provider(Endpoint("b", "openai", "http://y", "m"))
        _ = second._http_client()
        wrap.switch(second, Endpoint("b", "openai", "http://y", "m"))
        # the old (first) client is scheduled to close; let the loop drain it
        await asyncio.sleep(0)
        assert first._client is None, "switch must close the predecessor"
        assert wrap._provider is second

        await wrap.aclose()
        assert second._client is None, "aclose must close the active brain provider"

    asyncio.run(run())


# ------------------------------------------------------------------------- REL-6/7 run lifecycle (TG4.3)
# The problems: the runner task ref was discarded (GC risk, no cancel handle); agent_active
# cleared only in finally so a hung run wedged the dashboard forever (409 on every new run);
# no overall wall-clock timeout so a trickling target hung indefinitely; the SSE queue was
# unbounded. The original design's correct behavior — a run keeps draining server-side after
# the client disconnects — must be preserved (the audit praised it; REL-6 only bounds memory).

def _agent_run_app(monkeypatch, tmp_path, provider_obj, *, run_timeout_s=None):
    """Wire an app whose dashboard agent_run uses `provider_obj` as the brain, and return the
    TestClient + the sessions dir so tests can inspect the run log."""
    import wallbreaker.providers.factory as factory_mod
    import wallbreaker.tools as tools_mod
    from wallbreaker.config import Config, Endpoint
    from wallbreaker.providers.base import Provider
    from wallbreaker.tools.registry import ToolContext, ToolRegistry

    sessions = tmp_path / "sessions"
    sessions.mkdir()
    attacker = Endpoint("attacker", "openai", "http://attacker", "attack-model")
    target = Endpoint("target", "openai", "http://target", "target-model")
    cfg = Config(
        default_profile="attacker", profiles={"attacker": attacker},
        target=target, path=tmp_path / "config.toml",
    )
    registry = ToolRegistry(ToolContext(config=cfg))
    monkeypatch.setattr(factory_mod, "build_provider", lambda _endpoint: provider_obj)
    monkeypatch.setattr(tools_mod, "build_registry", lambda _config: registry)
    app = create_app(config=cfg, sessions_dir=sessions, require_auth=False)
    client = TestClient(app)
    return client, sessions, app


class _TricklingProvider(Provider):
    """Never yields a StopEvent — the round (and thus the run) hangs until the overall
    wall-clock timeout cancels it. Models the REL-7 trickling-target threat."""

    def __init__(self, endpoint):
        super().__init__(endpoint)

    async def stream(self, messages, tools=None, system=None, max_tokens=4096, temperature=None):
        # Yield one tiny delta then hang forever — so we don't return before the timeout
        # fires, and the run genuinely can't complete on its own.
        from wallbreaker.agent.messages import TextDelta
        yield TextDelta("thinking")
        await asyncio.Event().wait()  # never set


def test_overall_timeout_trips_on_a_trickling_target(monkeypatch, tmp_path):
    """TG4.9: a target that never returns (trickle/hang) trips the overall wall-clock timeout
    instead of hanging the run forever; a terminal 'timeout' SSE event is emitted."""
    provider = _TricklingProvider(Endpoint("attacker", "openai", "http://attacker", "attack-model"))
    body = {"objective": "go", "max_rounds": 5, "run_timeout_s": 1}  # 1s deadline
    client, sessions, _app = _agent_run_app(monkeypatch, tmp_path, provider, run_timeout_s=1)

    with client.stream("POST", "/api/agent/run", json=body) as response:
        assert response.status_code == 200
        stream_text = "".join(response.iter_text())

    assert '"status": "timeout"' in stream_text, "must emit a terminal timeout SSE event"
    # The run must have ended cleanly (agent_active cleared) — a new run can start (409 gone).
    r2 = client.post("/api/agent/run", json={"objective": "again", "max_rounds": 1, "run_timeout_s": 1})
    # 409 means still active (wedged) — must NOT happen; a stream response is 200.
    assert r2.status_code != 409, "agent_active must be cleared after a timed-out run"


def test_force_stop_ends_a_wedged_run_and_new_run_can_start(monkeypatch, tmp_path):
    """TG4.9: /api/agent/stop cancels a wedged/hung run; agent_active clears; a new run can
    start immediately after. The stop endpoint is idempotent (200 {stopped:false} when idle).

    Drives the ASGI app with httpx.AsyncClient + ASGITransport on ONE event loop so the
    background runner task and the stop request genuinely share state (Starlette's
    synchronous TestClient runs each request on a fresh loop, so agent_active set by one
    request is invisible to another). A controllable provider blocks the run on an Event
    until the test releases it, so the stop request lands while the run is genuinely active."""
    import httpx

    release = asyncio.Event()

    class _BlockedProvider(Provider):
        async def stream(self, messages, tools=None, system=None, max_tokens=4096, temperature=None):
            from wallbreaker.agent.messages import TextDelta
            yield TextDelta("thinking")
            await release.wait()  # held until the test releases (or the run is cancelled)

    provider = _BlockedProvider(Endpoint("attacker", "openai", "http://attacker", "attack-model"))
    client_sync, sessions, app = _agent_run_app(monkeypatch, tmp_path, provider)

    async def scenario():
        import httpx
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as ac:
            # Run a slow stream consumer and the stop request concurrently on this one loop.
            # The consumer iterates the SSE body slowly (one chunk then awaits), which drives the
            # StreamingResponse body generator and lets the background runner task actually
            # start. The stop task waits a beat for the runner to set agent_active=True, then
            # cancels it. Both share the loop so agent_active is visible to the stop request.
            stopped_result = {}
            run_done = asyncio.Event()

            async def consume_run():
                async with ac.stream("POST", "/api/agent/run",
                                     json={"objective": "go", "max_rounds": 5, "run_timeout_s": 600}) as r:
                    assert r.status_code == 200
                    # Pull exactly one chunk so the body generator runs and the runner starts,
                    # then hold the stream open (don't fully drain) until stop releases us.
                    got_one = False
                    async for chunk in r.aiter_raw():
                        got_one = True
                        break
                    assert got_one, "the run stream must emit at least one chunk"
                    await run_done.wait()
                    # The stream was cancelled; just exit — no second iteration.

            async def do_stop():
                await asyncio.sleep(0.1)  # let the runner start + set agent_active
                stop = await ac.post("/api/agent/stop")
                stopped_result["status"] = stop.status_code
                stopped_result["body"] = stop.json()
                release.set()  # unblock the provider so the cancelled runner exits promptly
                run_done.set()

            await asyncio.gather(consume_run(), do_stop())
            assert stopped_result.get("status") == 200
            assert stopped_result.get("body") == {"stopped": True}, "a running task must be stopped"

            # Idempotent: stopping again when nothing is running returns {stopped: false}.
            stop2 = await ac.post("/api/agent/stop")
            assert stop2.status_code == 200
            assert stop2.json() == {"stopped": False}

            # A new run can start immediately (agent_active cleared). Swap to a quick brain.
            from wallbreaker.agent.messages import StopEvent, TextDelta, ToolUseEvent
            import wallbreaker.providers.factory as factory_mod

            class _FinishQuickly(Provider):
                async def stream(self, messages, tools=None, system=None, max_tokens=4096, temperature=None):
                    yield TextDelta("done")
                    yield ToolUseEvent("f-1", "finish", {"summary": "ok"})
                    yield StopEvent("tool_use")
            monkeypatch.setattr(factory_mod, "build_provider", lambda _e: _FinishQuickly(Endpoint("a", "openai", "http://x", "m")))
            async with ac.stream("POST", "/api/agent/run",
                                 json={"objective": "again", "max_rounds": 1, "run_timeout_s": 30}) as r2:
                assert r2.status_code == 200
                body = "".join([seg async for seg in r2.aiter_text()])
            assert '"type": "done"' in body

    asyncio.run(scenario())


def test_client_disconnect_lets_run_finish_server_side(monkeypatch, tmp_path):
    """TG4.9 regression guard (PM directive): a client that disconnects mid-stream must NOT
    abandon the inference — the run completes server-side (its run log records agent_done),
    preserving the correct behavior the original audit praised. REL-6 bounds memory, it does
    NOT kill runs on disconnect."""
    from wallbreaker.agent.messages import StopEvent, TextDelta, ToolUseEvent

    class _FinishesAfterAStream(Provider):
        async def stream(self, messages, tools=None, system=None, max_tokens=4096, temperature=None):
            yield TextDelta("working")
            yield ToolUseEvent("f-1", "finish", {"summary": "completed server-side"})
            yield StopEvent("tool_use")

    provider = _FinishesAfterAStream(Endpoint("attacker", "openai", "http://attacker", "attack-model"))
    client, sessions, _app = _agent_run_app(monkeypatch, tmp_path, provider)

    # Open the stream, read only the first event, then close (disconnect) — don't drain it.
    stream_ctx = client.stream("POST", "/api/agent/run", json={"objective": "go", "max_rounds": 1})
    response = stream_ctx.__enter__()
    assert response.status_code == 200
    # Consume one SSE frame then drop the connection.
    _ = next(response.iter_lines(), None)
    stream_ctx.__exit__(None, None, None)  # disconnect

    # The runner kept going server-side; its run log must record a completed run. Poll briefly
    # (the runner is an async task; TestClient runs the event loop on each request).
    import time
    log = None
    deadline = time.monotonic() + 5.0
    while time.monotonic() < deadline and log is None:
        logs = list(sessions.glob("run-*.jsonl"))
        if logs:
            log = logs[0]
        else:  # nudge the loop with a cheap request so the runner task can progress
            client.get("/api/health")
    assert log is not None, "a run log must have been created"
    records = [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines() if line.strip()]
    statuses = [r.get("status") for r in records if r.get("kind") == "agent_done"]
    assert statuses, "the run must have completed server-side despite the client disconnect"
    assert statuses[0] in ("finished", "stopped", "timeout", "max_rounds", "error")


# ------------------------------------------------------------------------- RACE-2 ResultCache deltas + compaction (TG5.3)

def test_cache_v2_deltas_sum_on_load(tmp_path):
    """TG5.8: a fresh instance replaying a v2-delta file sums the deltas (not last-writer-wins),
    so multi-process interleaved writes no longer undercount."""
    import json as _json
    from wallbreaker.cache import ResultCache, _FORMAT_VERSION

    c = ResultCache(str(tmp_path))
    c.put("k", "COMPLIED", "r1")
    c.put("k", "REFUSED", "r2")
    c.put("k", "PARTIAL", "r3")
    c.put("k", "COMPLIED", "r4")
    del c
    # Simulate a second process: append a v2 delta for the SAME key directly to the file
    # (the multi-process case the lock-free RMW used to lose).
    with open(str(tmp_path / "wb_runs" / "result_cache.jsonl"), "a", encoding="utf-8") as fh:
        fh.write(_json.dumps({
            "key": "k", "v": _FORMAT_VERSION, "ds": 1, "dbucket": "complied",
            "last_response": "r5-from-other-process", "last_label": "COMPLIED",
        }) + "\n")
    reloaded = ResultCache(str(tmp_path))
    e = reloaded.get("k")
    assert e["samples"] == 5, "v2 deltas must SUM (4 in-process + 1 cross-process), not last-writer-wins"
    assert e["complied"] == 3  # r1, r4, r5
    assert e["refused"] == 1
    assert e["partial"] == 1
    assert e["last_response"] == "r5-from-other-process"


def test_cache_backward_compat_with_legacy_v1_cumulative_file(tmp_path):
    """An existing v1 (cumulative-snapshot) cache file must keep loading correctly after the
    TG5.3 delta change, and new v2 deltas append on top of it without double-counting (the #1
    rework risk the PM flagged)."""
    import json as _json
    from wallbreaker.cache import ResultCache, _FORMAT_VERSION

    # Hand-write a legacy v1 file: two cumulative snapshots for key 'k' (last one wins).
    path = tmp_path / "wb_runs" / "result_cache.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        _json.dumps({"key": "k", "samples": 1, "complied": 1, "partial": 0, "refused": 0,
                     "last_response": "old1", "last_label": "COMPLIED"}) + "\n"
        + _json.dumps({"key": "k", "samples": 2, "complied": 1, "partial": 0, "refused": 1,
                       "last_response": "old2", "last_label": "REFUSED"}) + "\n",
        encoding="utf-8",
    )
    c = ResultCache(str(tmp_path))
    e = c.get("k")
    assert e["samples"] == 2 and e["complied"] == 1 and e["refused"] == 1, "legacy v1 last-snapshot loads"
    assert e["last_label"] == "REFUSED"
    # A new put appends a v2 delta on top of the v1 snapshot — sums, not replaces.
    c.put("k", "COMPLIED", "new3")
    del c
    reloaded = ResultCache(str(tmp_path))
    e2 = reloaded.get("k")
    assert e2["samples"] == 3, "v1 snapshot (2) + v2 delta (1) = 3, no double-count"
    assert e2["complied"] == 2 and e2["refused"] == 1
    assert e2["last_response"] == "new3"


def test_cache_compaction_rewrites_as_one_line_per_key_and_preserves_totals(tmp_path):
    """TG5.3: once the file exceeds the compaction threshold it is rewritten (atomic) as one
    cumulative line per key, bounding on-disk growth without losing totals."""
    import json as _json
    from wallbreaker.cache import ResultCache
    import wallbreaker.cache as cache_mod

    c = ResultCache(str(tmp_path))
    # Force the threshold low so compaction triggers after a few puts.
    orig = cache_mod._COMPACTION_THRESHOLD
    cache_mod._COMPACTION_THRESHOLD = 5
    try:
        for i in range(8):
            c.put(f"key{i}", "COMPLIED", f"r{i}")
    finally:
        cache_mod._COMPACTION_THRESHOLD = orig

    # After compaction the file holds one line per key (8 keys), and totals survive reload.
    lines = [ln for ln in (tmp_path / "wb_runs" / "result_cache.jsonl").read_text().splitlines() if ln.strip()]
    assert len(lines) == 8, f"compacted to one line per key; got {len(lines)}"
    reloaded = ResultCache(str(tmp_path))
    assert reloaded.get("key0")["samples"] == 1 and reloaded.get("key7")["samples"] == 1
    assert reloaded.get("key3")["last_response"] == "r3"


# ------------------------------------------------------------------------- RACE-3 request_gate notify on raise (TG5.5)

def test_request_gate_notify_wakes_parked_tasks_on_limit_raise():
    """TG5.9: a task parked at the OLD limit (configure_request_gate(1,0) then 2 concurrent
    acquires) must proceed promptly when the limit is RAISED and notify_request_gates() runs,
    instead of staying blocked until an unrelated release()."""
    import asyncio
    from wallbreaker.providers.request_gate import (
        configure_request_gate, notify_request_gates, provider_request_slot,
    )

    configure_request_gate(1, 0)  # only one slot
    woke = asyncio.Event()
    started = asyncio.Event()

    async def first():
        async with provider_request_slot(_endpoint()):
            started.set()
            await woke.wait()  # hold the single slot until released

    async def parked():
        # Blocks at the limit until either a release or a notify-on-raise.
        async with provider_request_slot(_endpoint()):
            return True

    async def run():
        t1 = asyncio.create_task(first())
        await started.wait()
        t2 = asyncio.create_task(parked())
        # Give t2 a moment to park in acquire's condition.wait().
        await asyncio.sleep(0.05)
        assert not t2.done(), "parked task should be blocked at the limit"
        # Raise the limit and notify — t2 must proceed WITHOUT releasing t1.
        configure_request_gate(2, 0)
        await notify_request_gates()
        await asyncio.wait_for(t2, timeout=2.0)
        assert t2.done() and t2.result() is True, "parked task woke after the notify-on-raise"
        woke.set()
        await t1

    asyncio.run(run())


def test_request_gate_notify_is_noop_outside_loop_or_with_no_gates():
    """notify_request_gates must be safe to call with no running loop or no gates (no-op)."""
    import asyncio
    from wallbreaker.providers.request_gate import notify_request_gates
    # No running loop.
    asyncio.run(notify_request_gates())  # must not raise


def _endpoint(*, base_url="https://api.example/v1", key="shared"):
    from wallbreaker.config import Endpoint
    return Endpoint("one", "openai", base_url, "model", api_key=key)


# ------------------------------------------------------------------------- RACE-4 RunLog write serialization (TG5.4)

def test_runlog_write_is_serialized_and_lines_stay_atomic(tmp_path):
    """TG5.4: concurrent _write calls from coroutines do not interleave half-lines. The
    _write_lock + the 'no await inside _write' invariant guarantee line atomicity; this test
    fires many concurrent event() calls (each writes a line) and asserts every line is valid
    JSON with a unique, gap-free seq."""
    import asyncio
    from wallbreaker.session import RunLog

    log = RunLog(directory=str(tmp_path))
    N = 200

    async def writer(i):
        log.event("note", text=f"line-{i}")

    async def run():
        await asyncio.gather(*(writer(i) for i in range(N)))

    asyncio.run(run())
    import json as _json
    records = []
    for line in (tmp_path / log.path.name).read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        records.append(_json.loads(line))  # raises on a half-interleaved line
    notes = [r for r in records if r.get("kind") == "note"]
    seqs = [r["seq"] for r in notes]
    assert len(notes) == N, f"all {N} note lines present; got {len(notes)}"
    assert seqs == sorted(seqs), "seqs are monotonic (serialized, not interleaved)"
    assert len(set(seqs)) == N, "every seq is unique"


# ------------------------------------------------------------------------- SEC-11 / REL-8 input validation + error surfacing (TG3.4-3.6)

def _authed_client(tmp_path, **kw):
    """A TestClient with auth on + a valid token, so body-validation tests reach the handler."""
    from wallbreaker.config import Config, Endpoint
    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep, path=tmp_path / "config.toml")
    return TestClient(create_app(config=cfg, sessions_dir=tmp_path / "s", require_auth=True,
                                  auth_token="tok", **kw))


def test_malformed_agent_run_body_returns_4xx_not_500(tmp_path):
    """TG3.9 (SEC-11): a body with wrong-typed fields (max_rounds as a list) → 422, not a 500
    traceback. The Pydantic model catches it at the boundary before the handler can TypeError."""
    c = _authed_client(tmp_path)
    r = c.post("/api/agent/run", json={"objective": "go", "max_rounds": [1, 2]},
                 headers={"X-WB-Token": "tok"})
    assert r.status_code == 422, f"wrong-typed field must 422, got {r.status_code}"
    assert "traceback" not in r.text.lower()


def test_missing_objective_returns_4xx_not_500(tmp_path):
    """A body missing the required 'objective' field → 422 (Pydantic), not 500."""
    c = _authed_client(tmp_path)
    r = c.post("/api/agent/run", json={"max_rounds": 3}, headers={"X-WB-Token": "tok"})
    assert r.status_code == 422


def test_unknown_fields_do_not_422_valid_spa_traffic(tmp_path):
    """TG3.5: extra='ignore' on AgentRunRequest means the SPA can send unknown fields without
    a 422 — validates the PM's 'must not 422 valid SPA traffic' directive."""
    c = _authed_client(tmp_path)
    r = c.post("/api/agent/run",
               json={"objective": "go", "future_field": "no problem", "another": 42},
               headers={"X-WB-Token": "tok"})
    # The objective is valid; the run starts or 400s (no target configured) — but NOT 422 for extras.
    assert r.status_code != 422, "unknown fields must not 422 valid SPA traffic"


def test_global_500_handler_returns_generic_body_no_traceback(tmp_path):
    """TG3.9 (SEC-11): a forced internal error → generic 500 with no traceback/paths. Uses
    raise_server_exceptions=False so Starlette's error middleware doesn't re-raise."""
    from wallbreaker.config import Config, Endpoint
    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep, path=tmp_path / "config.toml")
    c = TestClient(create_app(config=cfg, sessions_dir=tmp_path / "s", require_auth=True,
                              auth_token="tok"), raise_server_exceptions=False)
    # Force a 500 by sending a valid objective but a config where the agent run will hit
    # an unexpected error. The simplest: monkeypatch run_autonomous to raise TypeError.
    import wallbreaker.agent.loop as loop_mod
    orig = loop_mod.run_autonomous

    async def boom(*a, **kw):
        raise TypeError("forced internal error with /tmp/secret/path in it")
    loop_mod.run_autonomous = boom
    try:
        with c.stream("POST", "/api/agent/run", json={"objective": "go", "max_rounds": 1},
                       headers={"X-WB-Token": "tok"}) as r:
            # The stream should complete (the runner catches the error) OR the handler 500s.
            text = "".join(r.iter_text())
    finally:
        loop_mod.run_autonomous = orig
    # The runner's except catches it and emits an error SSE event, so the stream completes.
    # But if the error propagated (e.g. before StreamingResponse started), the global handler
    # returns a generic 500. Either way: no traceback/paths in the response.
    assert "/tmp/secret/path" not in text, "internal path must not leak to the client"
    assert "traceback" not in text.lower()


def test_http_exception_not_intercepted_by_500_handler(tmp_path):
    """TG3.4: HTTPException (401/403/404/400) must keep its default handling — the Exception
    handler must NOT turn a 401 into a 500."""
    c = _authed_client(tmp_path)
    # No token → 401 (from SecurityMiddleware, which runs before the handler).
    r = c.get("/api/config")
    assert r.status_code == 401, f"missing token must be 401, not 500; got {r.status_code}"
    # Cross-site Origin → 403.
    r2 = c.get("/api/config", headers={"X-WB-Token": "tok", "Origin": "https://evil.example"})
    assert r2.status_code == 403
    # Unknown provider → 404.
    r3 = c.get("/api/providers/nonexistent", headers={"X-WB-Token": "tok"})
    assert r3.status_code == 404


def test_startup_degrades_log_and_continue_on_bad_config(tmp_path, monkeypatch):
    """TG3.6 (REL-8): a broken config no longer silently swallows — the init narrows to a
    logged warning and the dashboard boots with degraded state (provider_registry=None →
    provider routes return 400), not a hard crash."""
    from wallbreaker.config import Config, Endpoint
    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep, path=tmp_path / "config.toml")
    # Break ProviderRegistry so the init try-block fails.
    import wallbreaker.provider_registry as pr_mod
    orig_init = pr_mod.ProviderRegistry.__init__

    def boom(self, *a, **kw):
        raise OSError("simulated registry init failure")
    monkeypatch.setattr(pr_mod.ProviderRegistry, "__init__", boom)
    # The app must still create (log-and-continue, not hard-raise).
    app = create_app(config=cfg, sessions_dir=tmp_path / "s", require_auth=False)
    c = TestClient(app)
    # provider routes degrade to 400 (provider_registry is None).
    r = c.get("/api/providers")
    assert r.status_code in (200, 400), "degraded but not crashed"
    monkeypatch.setattr(pr_mod.ProviderRegistry, "__init__", orig_init)


# --------------------------------------------------------------- P3.1 DNS-rebind socket-IP-pinning
import ipaddress as _ipaddr
from unittest.mock import AsyncMock, MagicMock, patch


def test_pinned_backend_blocks_literal_private_ip():
    """PinnedEgressBackend rejects a direct connect to a private IP."""
    from wallbreaker.tools.egress_guard import PinnedEgressBackend, EgressBlocked

    inner = MagicMock()
    backend = PinnedEgressBackend(inner)

    for bad_ip in ["127.0.0.1", "10.0.0.1", "169.254.169.254", "::1"]:
        with pytest.raises(EgressBlocked, match="non-public"):
            asyncio.run(backend.connect_tcp(bad_ip, 443))
    inner.connect_tcp.assert_not_called()


def test_pinned_backend_passes_literal_public_ip():
    """PinnedEgressBackend allows a direct connect to a public IP."""
    from wallbreaker.tools.egress_guard import PinnedEgressBackend

    inner = MagicMock()
    inner.connect_tcp = AsyncMock(return_value=MagicMock())
    backend = PinnedEgressBackend(inner)

    asyncio.run(backend.connect_tcp("8.8.8.8", 443))
    inner.connect_tcp.assert_called_once_with("8.8.8.8", 443, timeout=None, local_address=None, socket_options=None)


def test_pinned_backend_resolves_and_pins_hostname():
    """PinnedEgressBackend resolves a hostname, validates all IPs, connects to the first."""
    from wallbreaker.tools.egress_guard import PinnedEgressBackend

    inner = MagicMock()
    inner.connect_tcp = AsyncMock(return_value=MagicMock())
    backend = PinnedEgressBackend(inner)

    # Mock getaddrinfo to return two public IPs
    fake_infos = [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.35", 443)),
    ]
    with patch("wallbreaker.tools.egress_guard.socket.getaddrinfo", return_value=fake_infos):
        asyncio.run(backend.connect_tcp("example.com", 443))

    # Should connect to the first validated IP, not the hostname
    inner.connect_tcp.assert_called_once()
    call_args = inner.connect_tcp.call_args
    assert call_args.args[0] == "93.184.216.34", "should pin to first resolved IP"
    assert call_args.args[1] == 443


def test_pinned_backend_blocks_dns_rebind():
    """If DNS returns a private IP alongside public ones, PinnedEgressBackend blocks."""
    from wallbreaker.tools.egress_guard import PinnedEgressBackend, EgressBlocked

    inner = MagicMock()
    backend = PinnedEgressBackend(inner)

    # Simulate DNS rebind: public + private addresses mixed
    fake_infos = [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("93.184.216.34", 443)),
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("169.254.169.254", 443)),
    ]
    with patch("wallbreaker.tools.egress_guard.socket.getaddrinfo", return_value=fake_infos):
        with pytest.raises(EgressBlocked, match="DNS rebind"):
            asyncio.run(backend.connect_tcp("evil.com", 443))

    inner.connect_tcp.assert_not_called()


def test_pinned_backend_blocks_all_private_resolution():
    """If DNS resolves to only private IPs, PinnedEgressBackend blocks."""
    from wallbreaker.tools.egress_guard import PinnedEgressBackend, EgressBlocked

    inner = MagicMock()
    backend = PinnedEgressBackend(inner)

    fake_infos = [
        (socket.AF_INET, socket.SOCK_STREAM, socket.IPPROTO_TCP, "", ("10.0.0.1", 443)),
    ]
    with patch("wallbreaker.tools.egress_guard.socket.getaddrinfo", return_value=fake_infos):
        with pytest.raises(EgressBlocked, match="DNS rebind"):
            asyncio.run(backend.connect_tcp("internal.local", 443))


def test_make_pinned_transport_wraps_backend():
    """make_pinned_transport creates a transport with PinnedEgressBackend."""
    from wallbreaker.tools.egress_guard import make_pinned_transport, PinnedEgressBackend

    transport = make_pinned_transport()
    assert isinstance(transport._pool._network_backend, PinnedEgressBackend)
    # Inner backend should be the default AutoBackend
    assert hasattr(transport._pool._network_backend._inner, "connect_tcp")


def test_http_tool_uses_pinned_transport():
    """The http_request tool should use a pinned transport (regression guard)."""
    import inspect
    from wallbreaker.tools import http_tool

    src = inspect.getsource(http_tool._http_request)
    assert "make_pinned_transport" in src, "http_request must use pinned transport"


# --------------------------------------------------------------- P3.4 REL-13 retry cap for non-idempotent generation
from wallbreaker.providers.request_gate import (
    gated_stream, gated_request, _MAX_ATTEMPTS, _MAX_ATTEMPTS_NON_IDEMPOTENT,
    is_concurrency_limit, ProviderError,
)


def test_rel13_non_idempotent_retry_cap_is_lower():
    """REL-13: the non-idempotent retry cap is lower than the default."""
    assert _MAX_ATTEMPTS_NON_IDEMPOTENT < _MAX_ATTEMPTS
    assert _MAX_ATTEMPTS_NON_IDEMPOTENT <= 2, "non-idempotent retries must be at most 2"


def test_rel13_gated_stream_respects_max_attempts():
    """gated_stream with max_attempts=1 should NOT retry on a 429."""
    from wallbreaker.config import Endpoint

    call_count = 0

    async def failing_factory():
        nonlocal call_count
        call_count += 1
        raise ProviderError("429: concurrent requests rate limit exceeded")
        yield  # noqa: unreachable — makes this an async generator

    ep = Endpoint("test", "openai", "http://test", "model")
    with pytest.raises(ProviderError):
        asyncio.run(_consume_stream(gated_stream(ep, failing_factory, max_attempts=1)))
    assert call_count == 1, "max_attempts=1 should not retry"


def test_rel13_gated_stream_no_retry_after_yielded_tokens():
    """REL-13: if any tokens were already yielded, a 429 must NOT retry
    (the generation already started billing). The error propagates to the caller
    but the stream factory is called only once."""
    from wallbreaker.config import Endpoint
    from wallbreaker.agent.messages import TextDelta

    call_count = 0

    async def partial_factory():
        nonlocal call_count
        call_count += 1
        yield TextDelta("partial")
        raise ProviderError("429: rate limit exceeded")

    ep = Endpoint("test", "openai", "http://test", "model")
    # The ProviderError propagates (the 429 after partial output is not swallowed),
    # but the factory is called only once — no retry.
    with pytest.raises(ProviderError):
        asyncio.run(_consume_stream(gated_stream(ep, partial_factory)))
    assert call_count == 1, "must not retry after tokens were yielded"


def test_rel13_is_concurrency_limit_is_narrow():
    """is_concurrency_limit only matches 429s with 'concurrent' or 'rate limit exceeded',
    NOT 'insufficient_quota' (which is a billing error, not a transient concurrency limit)."""
    assert is_concurrency_limit(Exception("429: Too many concurrent requests")) is True
    assert is_concurrency_limit(Exception("429: Rate limit exceeded")) is True
    assert is_concurrency_limit(Exception("429: insufficient_quota")) is False
    assert is_concurrency_limit(Exception("500: internal")) is False
    assert is_concurrency_limit(Exception("429:")) is False


async def _consume_stream(aiter):
    """Collect all items from an async iterator into a list."""
    out = []
    async for item in aiter:
        out.append(item)
    return out
