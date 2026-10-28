param([int]$Port = 8790, [switch]$NoBrowser)
$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $here
$py = (Get-Command python).Source
if (-not $NoBrowser) { Start-Process "http://127.0.0.1:$Port/" }
& $py -m uvicorn server:app --host 127.0.0.1 --port $Port
