# Wallbreaker Desktop quick launcher (PowerShell)
$ErrorActionPreference = "Stop"
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()

$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root
$env:WALLBREAKER_ROOT = $Root

Write-Host ""
Write-Host " ============================================" -ForegroundColor Cyan
Write-Host "  Wallbreaker Desktop  quick start" -ForegroundColor Cyan
Write-Host "  Root: $Root" -ForegroundColor DarkGray
Write-Host " ============================================" -ForegroundColor Cyan
Write-Host ""

$venvPython = Join-Path $Root ".venv\Scripts\python.exe"
if (Test-Path $venvPython) {
  $env:Path = "$(Join-Path $Root '.venv\Scripts');$env:Path"
}

function Assert-Cmd($name) {
  if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
    throw "$name not found. Install it and retry."
  }
}

Assert-Cmd node
Assert-Cmd npm

$desktopDir = Join-Path $Root "desktop"
if (-not (Test-Path (Join-Path $desktopDir "package.json"))) {
  throw "desktop\package.json missing."
}

# deps
if (-not (Test-Path (Join-Path $desktopDir "node_modules"))) {
  Write-Host "[1/3] Installing desktop dependencies..." -ForegroundColor Yellow
  Push-Location $desktopDir
  npm install
  Pop-Location
} else {
  Write-Host "[1/3] desktop node_modules OK" -ForegroundColor Green
}

# dashboard dist
$distIndex = Join-Path $Root "wallbreaker\dashboard\web\dist\index.html"
$webDir = Join-Path $Root "wallbreaker\dashboard\web"
if (-not (Test-Path $distIndex)) {
  Write-Host "[2/3] Building dashboard web UI..." -ForegroundColor Yellow
  if (-not (Test-Path (Join-Path $webDir "node_modules"))) {
    Push-Location $webDir
    npm install
    Pop-Location
  }
  Push-Location $webDir
  npm run build
  Pop-Location
} else {
  Write-Host "[2/3] dashboard dist OK" -ForegroundColor Green
}

Write-Host "[3/3] Launching desktop..." -ForegroundColor Yellow
Write-Host "      Close the window or press Ctrl+C here to stop." -ForegroundColor DarkGray
Write-Host ""

Push-Location $desktopDir
try {
  npm run dev
} finally {
  Pop-Location
}
