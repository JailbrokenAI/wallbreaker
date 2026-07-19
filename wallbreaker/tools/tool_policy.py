"""Tool-exposure policy for the browser-reachable dashboard agent.

The dashboard's `POST /api/agent/run` builds the full tool registry, which includes `run_shell`,
`write_file`/`edit_file`/`patch_file`, `read_file`, and `http_request`. Exposed with no auth that
was browser-CSRF-reachable RCE + arbitrary file read + SSRF (audit SEC-1/4/5). Even with auth
(added separately), least privilege says a browser-driven agent should not touch the host or read
arbitrary files by default. This module classifies tools and builds a filtered registry.

`run_shell` etc. remain available to the local CLI/TUI operator (their own authorized intent) and
to the dashboard only when the operator explicitly opts in (`allow_host_tools=True`).
"""
from __future__ import annotations

# Tools that can affect the host filesystem, run commands, or make arbitrary outbound requests.
HOST_AFFECTING = frozenset({
    "run_shell",
    "write_file",
    "edit_file",
    "patch_file",
    "read_file",
    "http_request",
})


def classify(tool_name: str) -> str:
    return "HOST_AFFECTING" if tool_name in HOST_AFFECTING else "SAFE"


def build_dashboard_registry(config, cwd: str | None = None, *, allow_host_tools: bool = False):
    """Build a tool registry for a dashboard-driven agent run.

    By default, host-affecting tools are removed so a browser-driven agent is confined to the
    attack/red-team toolset. When `allow_host_tools` is True (operator opt-in), the full registry
    is returned but reads are still confined to the working directory as defence-in-depth.
    """
    from . import build_registry

    # Pass cwd only when set so monkeypatched build_registry doubles (lambda _config: ...) still work.
    registry = build_registry(config) if cwd is None else build_registry(config, cwd=cwd)
    if allow_host_tools:
        # Keep host tools, but confine read_file to cwd so an opted-in agent still can't
        # exfiltrate ~/.env / keys outside the project (audit SEC-5).
        registry.ctx.confine_reads = True
        return registry

    for name in list(registry.names()):
        if name in HOST_AFFECTING:
            registry.remove(name)
    return registry
