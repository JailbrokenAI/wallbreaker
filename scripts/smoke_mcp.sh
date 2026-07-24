#!/usr/bin/env bash
# smoke_mcp.sh — Wallbreaker MCP smoke test
#
# Verifies both p4rs3lt0ngv3_mcp and wallbreaker_mcp server packages exist
# and their tools are callable. Tests tool functions directly (not MCP protocol,
# since that requires proper handshaking).
#
# Requires: bash, uv, python3 with wallbreaker + mcp installed
#
# Exits 0 on success, 1 on first failure.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Find uv
UV_BIN="${HOME}/.local/bin/uv"
if [[ ! -f "$UV_BIN" ]]; then
  if command -v uv >/dev/null 2>&1; then
    UV_BIN="uv"
  else
    echo "uv not found"
    exit 1
  fi
fi

cd "$REPO_ROOT"

PASS=0
FAIL=0

ok()   { echo "[OK] $*";   ((PASS++)) || true; }
fail() { echo "[FAIL] $*"; ((FAIL++)) || true; exit 1; }

# ── test 1: p4rs3lt0ngv3_mcp imports ─────────────────────────────────────────

if $UV_BIN run python3 -c "import p4rs3lt0ngv3_mcp; print('p4rs3lt0ngv3_mcp OK')" 2>/dev/null | grep -q "OK"; then
  ok "p4rs3lt0ngv3_mcp — imports successfully"
else
  fail "p4rs3lt0ngv3_mcp — import failed"
fi

# ── test 2: wallbreaker_mcp imports ──────────────────────────────────────────

if $UV_BIN run python3 -c "import wallbreaker_mcp; print('wallbreaker_mcp OK')" 2>/dev/null | grep -q "OK"; then
  ok "wallbreaker_mcp — imports successfully"
else
  fail "wallbreaker_mcp — import failed"
fi

# ── test 3: wb_seed_list is callable ─────────────────────────────────────────

RESULT=$($UV_BIN run python3 -c "
from wallbreaker_mcp.server import wb_seed_list
import json
result = wb_seed_list()
data = json.loads(result)
if isinstance(data, dict) and 'categories' in data:
  print('OK')
else:
  print('FAIL')
" 2>/dev/null || echo "ERROR")

if [[ "$RESULT" == "OK" ]]; then
  ok "wb_seed_list — returns JSON with categories"
else
  fail "wb_seed_list — call failed: $RESULT"
fi

# ── test 4: wb_judge is callable ────────────────────────────────────────────

RESULT=$($UV_BIN run python3 -c "
from wallbreaker_mcp.server import wb_judge
import json
result = wb_judge('test', 'I refuse')
data = json.loads(result)
if isinstance(data, dict) and 'score' in data and 'compliant' in data:
  print('OK')
else:
  print('FAIL')
" 2>/dev/null || echo "ERROR")

if [[ "$RESULT" == "OK" ]]; then
  ok "wb_judge — returns score and compliant"
else
  fail "wb_judge — call failed: $RESULT"
fi

# ── test 5: wb_generate_payloads is callable ────────────────────────────────

RESULT=$($UV_BIN run python3 -c "
from wallbreaker_mcp.server import wb_generate_payloads
import json
result = wb_generate_payloads('test', n=2)
data = json.loads(result)
if isinstance(data, dict) and 'payloads' in data and isinstance(data['payloads'], list):
  print('OK')
else:
  print('FAIL')
" 2>/dev/null || echo "ERROR")

if [[ "$RESULT" == "OK" ]]; then
  ok "wb_generate_payloads — returns payloads list"
else
  fail "wb_generate_payloads — call failed: $RESULT"
fi

# ── test 6: wb_attack is callable (no API key, should error gracefully) ──────

RESULT=$($UV_BIN run python3 -c "
from wallbreaker_mcp.server import wb_attack
import json
result = wb_attack('test', 'openai/gpt-4')
data = json.loads(result)
if isinstance(data, dict) and 'error' in data and 'success' in data:
  print('OK')
else:
  print('FAIL')
" 2>/dev/null || echo "ERROR")

if [[ "$RESULT" == "OK" ]]; then
  ok "wb_attack — returns error when no API key (graceful degradation)"
else
  fail "wb_attack — call failed: $RESULT"
fi

# ── summary ──────────────────────────────────────────────────────────────────

echo ""
if [[ "$FAIL" -eq 0 ]]; then
  echo "Smoke test passed. ($PASS checks)"
  exit 0
else
  echo "Smoke test FAILED. ($PASS passed, $FAIL failed)"
  exit 1
fi
