# Download and unpack the processed data + trained model released alongside the code, so the app runs
# without re-running the pipeline (no Earth Engine account needed).
#   .\scripts\fetch_data.ps1 -Url https://github.com/<org>/<repo>/releases/download/v1.0.0/floodevac-data-v1.0.0.zip
param([Parameter(Mandatory = $true)][string]$Url)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$tmp = Join-Path $env:TEMP "floodevac-data.zip"
Invoke-WebRequest -Uri $Url -OutFile $tmp
Expand-Archive -Path $tmp -DestinationPath $root -Force
Remove-Item $tmp
Write-Host "Data and model unpacked into $root\data\processed and $root\models"
