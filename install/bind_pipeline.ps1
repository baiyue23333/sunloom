param(
  [string]$ComfyUrl = "",
  [string]$ComfyDir = "",
  [switch]$StartServer,
  [int]$Port = 8770
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$cfgPath = Join-Path $root "station/data/config.json"
if (-not (Test-Path $cfgPath)) { throw "config.json not found - run install/install.ps1 first" }
$cfg = Get-Content $cfgPath -Raw | ConvertFrom-Json
if ($ComfyDir) { $cfg | Add-Member -NotePropertyName comfy_dir -NotePropertyValue $ComfyDir -Force }
if ($ComfyUrl) { $cfg | Add-Member -NotePropertyName comfy_url -NotePropertyValue $ComfyUrl -Force }
$cfg | ConvertTo-Json -Depth 6 | Set-Content -Encoding UTF8 $cfgPath

$url = ($cfg.comfy_url).TrimEnd('/')
Write-Host "ComfyUI: $url"
try { $stats = Invoke-RestMethod "$url/system_stats" -TimeoutSec 5 }
catch { throw "ComfyUI is not reachable. Start ComfyUI first (recommended 0.3.60+, tested on 0.42.x)." }
Write-Host ("ComfyUI " + $stats.system.comfyui_version + " OK, devices: " + (($stats.devices | ForEach-Object { $_.name }) -join ", "))

$missing = @()
$dir = $cfg.comfy_dir
if ($dir) {
  $checks = @(
    @{ folder = "models/checkpoints"; name = $cfg.model.unet_name },
    @{ folder = "models/diffusion_models"; name = $cfg.model.unet_name },
    @{ folder = "models/text_encoders"; name = $cfg.model.clip_name },
    @{ folder = "models/clip"; name = $cfg.model.clip_name },
    @{ folder = "models/vae"; name = $cfg.model.vae_name }
  )
  $found = @{}
  foreach ($c in $checks) {
    $p = Join-Path (Join-Path $dir $c.folder) $c.name
    if (Test-Path $p) { $found[$c.name] = $true }
  }
  foreach ($n in @($cfg.model.unet_name, $cfg.model.clip_name, $cfg.model.vae_name)) {
    if ($n -and -not $found.ContainsKey($n)) { $missing += $n }
  }
}

$info = Invoke-RestMethod "$url/object_info" -TimeoutSec 60
$required = @("UNETLoader","CLIPLoader","VAELoader","CLIPTextEncode","EmptyLatentImage","KSampler","VAEDecode","SaveImage","LoadImage","VAEEncode","SetLatentNoiseMask","LoraLoaderModelOnly")
$missNodes = @()
foreach ($n in $required) { if (-not $info.PSObject.Properties.Name.Contains($n)) { $missNodes += $n } }

Write-Host ""
Write-Host "== binding report ==" -ForegroundColor Cyan
if ($missing.Count) { Write-Host ("model files not found: " + ($missing -join ", ")) -ForegroundColor Yellow }
else { Write-Host "model files: OK" -ForegroundColor Green }
if ($missNodes.Count) { Write-Host ("missing nodes: " + ($missNodes -join ", ")) -ForegroundColor Red }
else { Write-Host "required nodes: OK" -ForegroundColor Green }

if ($StartServer) {
  Start-Process -FilePath "powershell" -ArgumentList "-NoExit","-File",(Join-Path $root "station/start.ps1"),"-Port",$Port
  Write-Host "server starting at http://127.0.0.1:$Port/"
}
if ($missing.Count -or $missNodes.Count) { exit 1 }
exit 0
