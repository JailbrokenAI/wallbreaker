"""TG5 Hardening Toolkit Extraction tests (R-G1).

Verifies that agent_dashboard_harden:
  - re-exports all required symbols as the exact same objects
  - provides importable pbt_fixtures module
  - maintains zero behavior change for auth, egress, and tool policy
"""
from __future__ import annotations

import os
import stat

import pytest


# ---------------------------------------------------------------------------
# 5.1 — Re-export parity (same object identity)
# ---------------------------------------------------------------------------

class TestReExportParity:
    """Symbols from agent_dashboard_harden must be identical to the source objects."""

    def test_security_middleware_is_same_object(self):
        from agent_dashboard_harden import SecurityMiddleware as harden_SM
        from wallbreaker.dashboard.auth import SecurityMiddleware as source_SM
        assert harden_SM is source_SM

    def test_ensure_launch_token_is_same_object(self):
        from agent_dashboard_harden import ensure_launch_token as harden_fn
        from wallbreaker.dashboard.auth import ensure_launch_token as source_fn
        assert harden_fn is source_fn

    def test_origin_is_same_site_is_same_object(self):
        from agent_dashboard_harden import origin_is_same_site as harden_fn
        from wallbreaker.dashboard.auth import origin_is_same_site as source_fn
        assert harden_fn is source_fn

    def test_token_file_path_is_same_object(self):
        from agent_dashboard_harden import token_file_path as harden_fn
        from wallbreaker.dashboard.auth import token_file_path as source_fn
        assert harden_fn is source_fn

    def test_egress_blocked_is_same_object(self):
        from agent_dashboard_harden import EgressBlocked as harden_cls
        from wallbreaker.tools.egress_guard import EgressBlocked as source_cls
        assert harden_cls is source_cls

    def test_check_url_is_same_object(self):
        from agent_dashboard_harden import check_url as harden_fn
        from wallbreaker.tools.egress_guard import check_url as source_fn
        assert harden_fn is source_fn

    def test_pinned_egress_backend_is_same_object(self):
        from agent_dashboard_harden import PinnedEgressBackend as harden_cls
        from wallbreaker.tools.egress_guard import PinnedEgressBackend as source_cls
        assert harden_cls is source_cls

    def test_make_pinned_transport_is_same_object(self):
        from agent_dashboard_harden import make_pinned_transport as harden_fn
        from wallbreaker.tools.egress_guard import make_pinned_transport as source_fn
        assert harden_fn is source_fn

    def test_build_dashboard_registry_is_same_object(self):
        from agent_dashboard_harden import build_dashboard_registry as harden_fn
        from wallbreaker.tools.tool_policy import build_dashboard_registry as source_fn
        assert harden_fn is source_fn


# ---------------------------------------------------------------------------
# 5.1 — Behavioral parity: SecurityMiddleware blocks correctly via re-export
# ---------------------------------------------------------------------------

class TestSecurityMiddlewareParity:
    """The re-exported SecurityMiddleware must gate requests identically."""

    def _client(self, **kw):
        from fastapi.testclient import TestClient
        from wallbreaker.dashboard.server import create_app
        return TestClient(create_app(config=None, sessions_dir="sessions", **kw),
                          raise_server_exceptions=False)

    def test_reexported_middleware_blocks_missing_token(self):
        c = self._client(require_auth=True, auth_token="tok")
        assert c.get("/api/config").status_code == 401

    def test_reexported_middleware_allows_valid_token(self):
        c = self._client(require_auth=True, auth_token="tok")
        assert c.get("/api/config", headers={"X-WB-Token": "tok"}).status_code == 200

    def test_reexported_middleware_blocks_cross_site_origin(self):
        c = self._client(require_auth=True, auth_token="tok")
        r = c.get("/api/config", headers={"X-WB-Token": "tok",
                                           "Origin": "https://evil.example"})
        assert r.status_code == 403

    def test_reexported_middleware_allows_loopback_origin(self):
        c = self._client(require_auth=True, auth_token="tok")
        r = c.get("/api/config", headers={"X-WB-Token": "tok",
                                           "Origin": "http://127.0.0.1:8787"})
        assert r.status_code == 200


# ---------------------------------------------------------------------------
# 5.1 — Behavioral parity: token file 0600 via re-export
# ---------------------------------------------------------------------------

def test_ensure_launch_token_writes_0600(tmp_path):
    from agent_dashboard_harden import ensure_launch_token, token_file_path
    ensure_launch_token(tmp_path)
    mode = stat.S_IMODE(os.stat(token_file_path(tmp_path)).st_mode)
    assert mode == 0o600


# ---------------------------------------------------------------------------
# 5.1 — Behavioral parity: egress guard via re-export
# ---------------------------------------------------------------------------

class TestEgressGuardParity:
    def test_check_url_blocks_private_ip(self):
        from agent_dashboard_harden import EgressBlocked, check_url
        with pytest.raises(EgressBlocked):
            check_url("http://169.254.169.254/latest/meta-data/")

    def test_check_url_blocks_file_scheme(self):
        from agent_dashboard_harden import EgressBlocked, check_url
        with pytest.raises(EgressBlocked):
            check_url("file:///etc/passwd")

    def test_pinned_backend_blocks_private_literal(self):
        import asyncio
        from agent_dashboard_harden import EgressBlocked, PinnedEgressBackend
        from unittest.mock import MagicMock
        backend = PinnedEgressBackend(MagicMock())
        with pytest.raises(EgressBlocked):
            asyncio.run(backend.connect_tcp("127.0.0.1", 443))

    def test_make_pinned_transport_installs_pinned_backend(self):
        from agent_dashboard_harden import PinnedEgressBackend, make_pinned_transport
        transport = make_pinned_transport()
        assert isinstance(transport._pool._network_backend, PinnedEgressBackend)


# ---------------------------------------------------------------------------
# 5.1 — Behavioral parity: tool policy via re-export
# ---------------------------------------------------------------------------

def test_build_dashboard_registry_excludes_host_tools(monkeypatch):
    from types import SimpleNamespace
    from wallbreaker.tools import shell, files, http_tool
    from wallbreaker.tools.registry import ToolContext, ToolRegistry
    from wallbreaker.tools.tool_policy import HOST_AFFECTING
    import wallbreaker.tools as tools_mod

    def mini_registry(_config):
        reg = ToolRegistry(ToolContext(config=SimpleNamespace(), cwd="."))
        shell.register(reg)
        files.register(reg)
        http_tool.register(reg)
        return reg

    monkeypatch.setattr(tools_mod, "build_registry", mini_registry)
    from agent_dashboard_harden import build_dashboard_registry
    reg = build_dashboard_registry(SimpleNamespace())
    assert not (set(reg.names()) & HOST_AFFECTING), "host tools must be excluded"


# ---------------------------------------------------------------------------
# 5.2 — pbt_fixtures module is importable and factories return callables
# ---------------------------------------------------------------------------

class TestPbtFixturesModule:
    def test_all_factories_importable(self):
        from agent_dashboard_harden.pbt_fixtures import (
            make_access_control_property,
            make_corpus_integrity_property,
            make_data_integrity_property,
            make_input_validation_property,
            make_session_property,
        )
        assert all(callable(f) for f in [
            make_access_control_property,
            make_corpus_integrity_property,
            make_data_integrity_property,
            make_input_validation_property,
            make_session_property,
        ])

    def test_access_control_factory_returns_callable(self):
        from agent_dashboard_harden.pbt_fixtures import make_access_control_property
        fn = make_access_control_property(lambda token, origin, method: 401)
        assert callable(fn)

    def test_input_validation_factory_returns_callable(self):
        from agent_dashboard_harden import EgressBlocked
        from agent_dashboard_harden.pbt_fixtures import make_input_validation_property

        def validate(url):
            from agent_dashboard_harden import check_url
            check_url(url)

        fn = make_input_validation_property(validate)
        assert callable(fn)

    def test_corpus_integrity_factory_returns_callable(self):
        from agent_dashboard_harden.pbt_fixtures import make_corpus_integrity_property
        fn = make_corpus_integrity_property(lambda pinned, actual: pinned == actual)
        assert callable(fn)

    def test_session_factory_returns_callable(self):
        from agent_dashboard_harden.pbt_fixtures import make_session_property
        fn = make_session_property(lambda tmp_path: tmp_path / "tok")
        assert callable(fn)
