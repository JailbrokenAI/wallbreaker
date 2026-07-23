"""agent_dashboard_harden — re-export facade for the Wallbreaker security hardening toolkit.

This package re-exports security-critical symbols from their canonical locations so that
consuming projects can depend on a single, stable import path. No logic is duplicated here;
every symbol is the exact same object as in the source module.

Canonical locations:
  wallbreaker.dashboard.auth   → SecurityMiddleware, ensure_launch_token,
                                  origin_is_same_site, token_file_path
  wallbreaker.tools.egress_guard → EgressBlocked, check_url,
                                    PinnedEgressBackend, make_pinned_transport
  wallbreaker.tools.tool_policy  → build_dashboard_registry
"""
from __future__ import annotations

# --------------------------------------------------------------------------- auth
from wallbreaker.dashboard.auth import (
    SecurityMiddleware,
    ensure_launch_token,
    origin_is_same_site,
    token_file_path,
)

# --------------------------------------------------------------------------- egress_guard
from wallbreaker.tools.egress_guard import (
    EgressBlocked,
    check_url,
    PinnedEgressBackend,
    make_pinned_transport,
)

# --------------------------------------------------------------------------- tool_policy
from wallbreaker.tools.tool_policy import build_dashboard_registry

__all__ = [
    # auth
    "SecurityMiddleware",
    "ensure_launch_token",
    "origin_is_same_site",
    "token_file_path",
    # egress_guard
    "EgressBlocked",
    "check_url",
    "PinnedEgressBackend",
    "make_pinned_transport",
    # tool_policy
    "build_dashboard_registry",
]
