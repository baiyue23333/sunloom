param(
  [string]$Dir = "",
  [string]$Repo = "SmilingWolf/wd-eva02-large-tagger-v3",
  [string]$Python = "python"
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)
if (-not $Dir) { $Dir = Join-Path $root "station\data\wd14" }
Write-Host "== downloading WD14 tagger to $Dir ==" -ForegroundColor Cyan
& $Python -m pip install huggingface_hub
& $Python -c "from huggingface_hub import snapshot_download; snapshot_download(repo_id='$Repo', local_dir=r'$Dir')"
$cfg = Join-Path $root "station\data\config.json"
if (Test-Path $cfg) {
  & $Python -c "import json; p=r'$cfg'; d=json.load(open(p,encoding='utf-8')); d.setdefault('tagger',{})['model_dir']=r'$Dir'; json.dump(d,open(p,'w',encoding='utf-8'),ensure_ascii=False,indent=2); print('config updated')"
}
Write-Host "done. tagging page should now find the model." -ForegroundColor Green
