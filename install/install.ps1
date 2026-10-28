param(
  [string]$Python = "python",
  [string]$ComfyDir = "",
  [string]$Unet = "",
  [string]$Clip = "",
  [string]$Vae = "",
  [string]$ClipType = "stable_diffusion",
  [switch]$SkipDeps
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Write-Host "== SUNLOOM block studio installer ==" -ForegroundColor Cyan

$ver = & $Python -c "import sys;print('%d.%d' % sys.version_info[:2])"
if ([version]$ver -lt [version]"3.10") { throw "Python 3.10+ required, found $ver" }
Write-Host "python $ver OK"

if (-not $SkipDeps) {
  Write-Host "installing python packages..."
  & $Python -m pip install --upgrade pip | Out-Null
  & $Python -m pip install -r (Join-Path $root "requirements.txt")
  if ($LASTEXITCODE -ne 0) { throw "pip install failed" }
}

function Pick-FromDir([string]$dir, [string]$filter) {
  if (-not (Test-Path $dir)) { return @() }
  Get-ChildItem $dir -File -Filter $filter -ErrorAction SilentlyContinue | ForEach-Object { $_.Name }
}

while (-not $ComfyDir -or -not (Test-Path (Join-Path $ComfyDir "main.py"))) {
  $ComfyDir = Read-Host "Path to the ComfyUI folder (the one containing main.py)"
  if (-not $ComfyDir) { throw "ComfyUI path is required" }
}
Write-Host "ComfyUI: $ComfyDir"

function Choose([string]$label, [string[]]$names) {
  if (-not $names -or $names.Count -eq 0) { return Read-Host "$label (type the file name)" }
  Write-Host ""
  Write-Host "$label available:"
  for ($i = 0; $i -lt $names.Count; $i++) { Write-Host ("  [{0}] {1}" -f ($i + 1), $names[$i]) }
  $sel = Read-Host "choose a number (blank = type manually)"
  if ($sel -match '^\d+$' -and [int]$sel -ge 1 -and [int]$sel -le $names.Count) { return $names[[int]$sel - 1] }
  return Read-Host $label
}

$ckpts = @(Pick-FromDir (Join-Path $ComfyDir "models/checkpoints") "*.safetensors") + @(Pick-FromDir (Join-Path $ComfyDir "models/diffusion_models") "*.safetensors")
$texts = @(Pick-FromDir (Join-Path $ComfyDir "models/text_encoders") "*.safetensors") + @(Pick-FromDir (Join-Path $ComfyDir "models/clip") "*.safetensors")
$vaes  = @(Pick-FromDir (Join-Path $ComfyDir "models/vae") "*.safetensors")

if (-not $Unet) { $Unet = Choose "UNet / checkpoint" $ckpts }
if (-not $Clip) { $Clip = Choose "Text encoder" $texts }
if (-not $Vae)  { $Vae  = Choose "VAE" $vaes }

$cfg = Join-Path $root "station/data/config.json"
$obj = [ordered]@{
  comfy_url = "http://127.0.0.1:8188"
  comfy_dir = $ComfyDir
  model = [ordered]@{ unet_name = $Unet; clip_name = $Clip; vae_name = $Vae; clip_type = $ClipType }
  defaults = [ordered]@{ size = "1024x1536"; steps = 28; cfg = 5.5; sampler = "euler"; scheduler = "simple"; loras = @() }
  output_dir = "output"
}
New-Item -ItemType Directory -Force -Path (Split-Path $cfg) | Out-Null
$obj | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 $cfg
Write-Host ""
Write-Host "config written: $cfg" -ForegroundColor Green
Write-Host "next: install/bind_pipeline.ps1 to verify, then station/start.ps1"
