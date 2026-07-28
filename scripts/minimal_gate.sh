#!/usr/bin/env bash
# Minimal regression gate for Daedalus/wallbreaker operating engine.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
PY="${PYTHON:-python}"
if [[ -x "$ROOT/.venv/bin/python" ]]; then PY="$ROOT/.venv/bin/python"; fi
if [[ -x "$ROOT/.venv/Scripts/python.exe" ]]; then PY="$ROOT/.venv/Scripts/python.exe"; fi

echo "== minimal pytest gate =="
"$PY" -m pytest -q \
  tests/test_await_llm.py \
  tests/test_bug001_partial_salvage.py \
  tests/test_daedalus.py \
  tests/test_cyber_gate.py \
  tests/test_judging.py \
  tests/test_judge_selftest_metrics.py \
  tests/test_frr_scan.py \
  tests/test_liberation_embed.py \
  tests/test_liberation_inspect.py \
  tests/test_datasets.py \
  tests/test_datasets_refresh_cli.py \
  tests/test_relentless.py \
  tests/test_schedule_and_phase5_extras.py \
  tests/test_phase5_surfaces.py \
  tests/test_branding.py \
  tests/test_crescendo.py \
  tests/test_resolve_timeout.py \
  tests/test_bandit_defaults.py \
  tests/test_mutate_constraint_default.py \
  tests/test_external_embed.py

echo "== CLI smokes =="
"$PY" -m wallbreaker datasets list >/dev/null
"$PY" -m wallbreaker schedule list >/dev/null
"$PY" - <<'PY'
from wallbreaker.tools import build_registry
from wallbreaker.config import Config
names = set(build_registry(Config(default_profile="x", profiles={})).names())
need = {
    "crescendo", "image_crescendo", "frr_scan", "judge_selftest",
    "agentbench", "rug_pull", "worm_wrap", "query_image_target",
}
missing = sorted(need - names)
assert not missing, f"missing tools: {missing}"
print("tool registration ok:", ", ".join(sorted(need)))
PY
echo "== minimal gate green =="
