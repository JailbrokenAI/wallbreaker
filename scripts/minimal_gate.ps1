# Minimal regression gate (Windows PowerShell)
$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
if (-not $Root) { $Root = (Resolve-Path "$PSScriptRoot\..").Path }
Set-Location $Root
$env:PYTHONPATH = $Root
$Py = Join-Path $Root ".venv\Scripts\python.exe"
if (-not (Test-Path $Py)) { $Py = "python" }
Write-Host "== minimal pytest gate =="
& $Py -m pytest -q `
  tests/test_await_llm.py `
  tests/test_bug001_partial_salvage.py `
  tests/test_daedalus.py `
  tests/test_cyber_gate.py `
  tests/test_judging.py `
  tests/test_judge_selftest_metrics.py `
  tests/test_frr_scan.py `
  tests/test_liberation_embed.py `
  tests/test_liberation_inspect.py `
  tests/test_datasets.py `
  tests/test_datasets_refresh_cli.py `
  tests/test_relentless.py `
  tests/test_schedule_and_phase5_extras.py `
  tests/test_phase5_surfaces.py `
  tests/test_branding.py `
  tests/test_crescendo.py `
  tests/test_resolve_timeout.py `
  tests/test_bandit_defaults.py `
  tests/test_mutate_constraint_default.py `
  tests/test_external_embed.py
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
Write-Host "== CLI smokes =="
& $Py -m wallbreaker datasets list | Out-Null
& $Py -m wallbreaker schedule list | Out-Null
& $Py -c "from wallbreaker.tools import build_registry; from wallbreaker.config import Config; names=set(build_registry(Config(default_profile='x', profiles={})).names()); need={'crescendo','image_crescendo','frr_scan','judge_selftest','agentbench','rug_pull','worm_wrap'}; missing=sorted(need-names); assert not missing, missing; print('tool registration ok')"
Write-Host "== minimal gate green =="
