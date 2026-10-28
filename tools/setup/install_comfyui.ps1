param(
  [string]$Dir = "$HOME\ComfyUI",
  [string]$Tag = "v0.3.60",
  [string]$Python = "python",
  [switch]$Cpu
)
$ErrorActionPreference = "Stop"
Write-Host "== installing ComfyUI $Tag to $Dir ==" -ForegroundColor Cyan
if (-not (Get-Command git -ErrorAction SilentlyContinue)) { throw "git is required" }
if (-not (Test-Path $Dir)) {
  git clone --depth 1 --branch $Tag https://github.com/comfyanonymous/ComfyUI $Dir
} else {
  Write-Host "folder exists, skip clone"
}
$venvPy = Join-Path $Dir ".venv\Scripts\python.exe"
if (-not (Test-Path $venvPy)) { & $Python -m venv (Join-Path $Dir ".venv") }
& $venvPy -m pip install --upgrade pip
if ($Cpu) { & $venvPy -m pip install torch torchvision torchaudio }
& $venvPy -m pip install -r (Join-Path $Dir "requirements.txt")
Write-Host "ComfyUI ready: $Dir" -ForegroundColor Green
Write-Host "next: put models under $Dir\models, then run install/install.ps1 -ComfyDir"
