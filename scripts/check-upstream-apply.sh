#!/bin/bash
# check-upstream-apply.sh — verifies the security remediation branch applies cleanly.
#
# This script is the CI gate for the upstream-contrib/security-remediation branch.
# It confirms that all three Critical security fixes (SEC-1/2/3) and the two
# supporting security modules (egress_guard, tool_policy) are present and importable.
#
# Exit codes:
#   0 — all security symbols found; branch applies cleanly
#   1 — one or more symbols missing; apply has not landed or was reverted
set -e
cd "$(dirname "$0")/.."

echo "=== Upstream apply check: wallbreaker security remediation ==="
echo "Base commit (upstream JailbrokenAI/wallbreaker): bfd1d64"
echo ""

echo "[1/3] auth.py — SecurityMiddleware + ensure_launch_token (SEC-1/2/3)"
python -c "from wallbreaker.dashboard.auth import SecurityMiddleware, ensure_launch_token; print('  auth OK')"

echo "[2/3] egress_guard.py — PinnedEgressBackend + make_pinned_transport (SEC-4)"
python -c "from wallbreaker.tools.egress_guard import PinnedEgressBackend, make_pinned_transport; print('  egress OK')"

echo "[3/3] tool_policy.py — build_dashboard_registry (SEC-1/5)"
python -c "from wallbreaker.tools.tool_policy import build_dashboard_registry; print('  tool_policy OK')"

echo ""
echo "Upstream apply check: PASS"
echo "All Critical/High security symbols present on branch upstream-contrib/security-remediation"
