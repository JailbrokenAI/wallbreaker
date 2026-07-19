"""Focused + property-based tests for the audit-remediation hardening.

Covers: SEC-1/2/3/6 (auth+CSRF), SEC-1/4/5 (tool policy), SEC-4 (egress guard), SEC-5/10 (path
confinement), SEC-7 (bind guard), SEC-9 (log redaction + perms), REL-1 (vision_complete),
REL-3/RACE-1 (atomic state). Runs offline; no network, no real subprocess.
"""
from __future__ import annotations

import asyncio
import json
import os
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
    c = _client()  # require_auth defaults False
    body = c.get("/api/session").json()
    assert body["authenticated"] is False
    assert body["token"] == ""


def test_no_auth_mode_is_open_for_back_compat():
    c = _client()  # require_auth defaults False (test factory / embedders)
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
    app = create_app(config=cfg, sessions_dir=sessions)
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
