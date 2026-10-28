param(
  [Parameter(Mandatory=$true)][string]$Dataset,
  [Parameter(Mandatory=$true)][string]$OutputName,
  [string]$KohyaDir = "",
  [string]$BaseModel = "",
  [int]$Dim = 32,
  [int]$Epochs = 10,
  [int]$BatchSize = 1,
  [float]$LR = 1e-4,
  [string]$Trigger = "",
  [int]$SaveEvery = 2
)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent (Split-Path -Parent $here)

if (-not $KohyaDir) {
  $cfg = Join-Path $root "station/data/config.json"
  if (Test-Path $cfg) {
    $j = Get-Content $cfg -Raw | ConvertFrom-Json
    if ($j.kohya_dir) { $KohyaDir = $j.kohya_dir }
  }
}
if (-not $KohyaDir -or -not (Test-Path (Join-Path $KohyaDir "train_network.py"))) {
  throw "kohya sd-scripts not configured. Set kohya_dir in station/data/config.json (folder containing train_network.py)."
}
if (-not $BaseModel) {
  $cfg = Join-Path $root "station/data/config.json"
  $j = Get-Content $cfg -Raw | ConvertFrom-Json
  $BaseModel = $j.model.unet_name
  if (-not $BaseModel) { throw "BaseModel is required" }
}

$out = Join-Path $root ("station/data/train/" + $OutputName)
New-Item -ItemType Directory -Force -Path $out | Out-Null
$py = (Get-Command python).Source

$trainArgs = @(
  (Join-Path $KohyaDir "train_network.py"),
  "--pretrained_model_name_or_path", $BaseModel,
  "--train_data_dir", $Dataset,
  "--output_dir", $out,
  "--output_name", $OutputName,
  "--network_module", "networks.lora",
  "--network_dim", $Dim,
  "--max_train_epochs", $Epochs,
  "--train_batch_size", $BatchSize,
  "--learning_rate", $LR,
  "--save_every_n_epochs", $SaveEvery,
  "--save_precision", "fp16",
  "--mixed_precision", "fp16",
  "--cache_latents",
  "--noise_offset", 0.03
)
& $py @trainArgs
