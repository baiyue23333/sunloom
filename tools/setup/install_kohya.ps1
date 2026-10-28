param(
  [string]$Dir = "$HOME\sd-scripts",
  [string]$Python = "python"
)
$ErrorActionPreference = "Stop"
Write-Host "== installing kohya sd-scripts to $Dir ==" -ForegroundColor Cyan
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "git is required" }
if (-not (Test-Path $Dir)) { git clone --depth 1 https://github.com/kohya-ss/sd-scripts $Dir }
$venvPy = Join-Path $Dir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { & $Python -m venv (Join-Path $Dir ".venv") }
& $venvPy -m pip install --upgrade pip
& $venvPy -m pip install -r (Join-Path $Dir "requirements.txt")
Write-Host "kohya ready: $Dir" -ForegroundColor Green
Write-Host "set kohya_dir in station/data/config.json or use the Train page"
