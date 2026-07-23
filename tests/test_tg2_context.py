"""TG2 — ToolContext Decomposition tests (engine-capability-uplift).

Validates item B: EngagementContext + IOContext sub-contexts; delegating properties on
ToolContext (R-B1, R-B2, SP-DI5).  Zero tool signature changes — parity verified by
running the full suite (see tasks.md §2.4); this file covers the structural contracts.
"""
from __future__ import annotations

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

from wallbreaker.config import Config, Endpoint
from wallbreaker.tools.registry import EngagementContext, IOContext, ToolContext


def _cfg(tmp_path=None):
    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep,
                 path=(tmp_path / "cfg.toml") if tmp_path else None)
    return cfg


def _ctx(tmp_path=None, **kwargs) -> ToolContext:
    return ToolContext(config=_cfg(tmp_path), **kwargs)


# ---------------------------------------------------------------------------
# 2.4  Structural — sub-context objects created correctly
# ---------------------------------------------------------------------------

def test_toolcontext_has_engagement_and_io_subcontexts():
    """ToolContext exposes .engagement (EngagementContext) and .io (IOContext) (R-B1)."""
    ctx = _ctx()
    assert isinstance(ctx.engagement, EngagementContext)
    assert isinstance(ctx.io, IOContext)


def test_toolcontext_thin_direct_fields():
    """ToolContext thin fields: config, cwd, judge_endpoint, confine_reads (R-B1)."""
    ep = Endpoint("t", "openai", "http://x", "m")
    cfg = Config(default_profile="t", profiles={"t": ep}, target=ep)
    ctx = ToolContext(config=cfg, cwd="/tmp", judge_endpoint=ep, confine_reads=True)
    assert ctx.config is cfg
    assert ctx.cwd == "/tmp"
    assert ctx.judge_endpoint is ep
    assert ctx.confine_reads is True


# ---------------------------------------------------------------------------
# 2.5  Delegation parity — all legacy fields readable and writable via envelope
# ---------------------------------------------------------------------------

ENGAGEMENT_FIELDS = [
    ("current_objective", "my objective", ""),
    ("attacker_model", "gpt-5", ""),
    ("vault_enabled", False, True),
    ("target_system", "system prompt", None),
    ("target_reasoning", "chain of thought", ""),
]

IO_FIELDS = [
    ("progress", lambda s: None, None),
    ("record", lambda *a: None, None),
    ("run_events", lambda e: None, None),
    ("tool_logger", lambda *a: None, None),
]


@pytest.mark.parametrize("field,value,_default", ENGAGEMENT_FIELDS)
def test_engagement_field_delegation_read_write(field, value, _default):
    """Value set through ToolContext envelope is readable back through the property
    AND on the underlying EngagementContext (R-B2)."""
    ctx = _ctx()
    setattr(ctx, field, value)
    assert getattr(ctx, field) == value
    assert getattr(ctx.engagement, field) == value


@pytest.mark.parametrize("field,value,_default", IO_FIELDS)
def test_io_field_delegation_read_write(field, value, _default):
    """Value set through ToolContext envelope is readable back through the property
    AND on the underlying IOContext (R-B2)."""
    ctx = _ctx()
    setattr(ctx, field, value)
    assert getattr(ctx, field) is value
    assert getattr(ctx.io, field) is value


def test_target_thread_delegation():
    """target_thread delegates to engagement.target_thread."""
    ctx = _ctx()
    ctx.target_thread = [{"role": "user", "content": "hello"}]
    assert ctx.target_thread == [{"role": "user", "content": "hello"}]
    assert ctx.engagement.target_thread == ctx.target_thread


# ---------------------------------------------------------------------------
# 2.5 (cont.)  Legacy kwarg constructor compatibility
# ---------------------------------------------------------------------------

def test_legacy_kwargs_route_to_io():
    """ToolContext(config=..., progress=..., record=...) still works (R-B2 backward compat)."""
    messages = []
    records = []
    ctx = ToolContext(
        config=_cfg(),
        progress=messages.append,
        record=lambda *a: records.append(a),
    )
    ctx.emit("hello")
    assert messages == ["hello"]
    ctx.record_verdict("payload", "response", "REFUSED", "reason", "tech")
    assert records  # record was called


def test_legacy_kwargs_route_to_engagement():
    """ToolContext(config=..., current_objective=...) sets engagement fields (R-B2)."""
    ctx = ToolContext(
        config=_cfg(),
        current_objective="my goal",
        attacker_model="gpt-5",
        vault_enabled=False,
    )
    assert ctx.current_objective == "my goal"
    assert ctx.engagement.current_objective == "my goal"
    assert ctx.attacker_model == "gpt-5"
    assert ctx.vault_enabled is False


def test_emit_delegates_to_io_progress():
    """emit() calls io.progress (R-B2)."""
    msgs = []
    ctx = _ctx(progress=msgs.append)
    ctx.emit("test message")
    assert msgs == ["test message"]


def test_emit_silent_when_no_progress():
    """emit() is silent when io.progress is None."""
    ctx = _ctx()
    ctx.emit("no sink")  # must not raise


def test_run_returns_run_handle():
    """ctx.run() returns a RunHandle usable as context manager."""
    from wallbreaker.tools.registry import RunHandle
    ctx = _ctx()
    handle = ctx.run("test run", total=3)
    assert isinstance(handle, RunHandle)


# ---------------------------------------------------------------------------
# 2.6  SP-DI5 — PBT delegation parity
# ---------------------------------------------------------------------------

@settings(max_examples=200)
@given(
    field=st.sampled_from([
        "current_objective", "attacker_model",
        "target_system", "target_reasoning",
    ]),
    value=st.one_of(st.text(max_size=40), st.none()),
)
def test_context_delegation_parity_text(field, value):
    """A text value set through the ToolContext envelope reads back identically
    via the delegating property AND on the underlying EngagementContext (SP-DI5 / R-B2).
    """
    ctx = _ctx()
    setattr(ctx, field, value)
    assert getattr(ctx, field) == value
    assert getattr(ctx.engagement, field) == value


@settings(max_examples=100)
@given(value=st.booleans())
def test_context_delegation_parity_vault_enabled(value):
    """vault_enabled delegation parity (bool field) (SP-DI5)."""
    ctx = _ctx()
    ctx.vault_enabled = value
    assert ctx.vault_enabled == value
    assert ctx.engagement.vault_enabled == value


# ---------------------------------------------------------------------------
# 2.7 / 2.8  Readiness checks
# ---------------------------------------------------------------------------

def test_no_tool_file_edited_for_signatures(tmp_path):
    """Tools using ctx.current_objective and ctx.progress still work via delegation (§2.5)."""
    messages = []
    ctx = ToolContext(
        config=_cfg(tmp_path),
        cwd=str(tmp_path),
        progress=messages.append,
        current_objective="synthesize compound X",
    )
    # Read via delegating property (as a tool would)
    assert ctx.current_objective == "synthesize compound X"
    ctx.emit("doing work")
    assert "doing work" in messages


def test_new_tools_can_take_engagement_context_directly():
    """New TG6 agentic tools can accept EngagementContext directly (§2.8)."""
    ctx = _ctx(current_objective="agentic attack")
    eng: EngagementContext = ctx.engagement
    assert eng.current_objective == "agentic attack"
    # Sub-context is the same object, not a copy
    ctx.current_objective = "updated"
    assert eng.current_objective == "updated"
