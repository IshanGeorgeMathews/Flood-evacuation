# Start FloodEvac Ernakulam and open it in the browser.
#   Right-click > Run with PowerShell, or:  powershell -ExecutionPolicy Bypass -File .\start.ps1
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
$py = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  Write-Host "First run: creating the Python environment (a few minutes)..."
  python -m venv .venv
  & $py -m pip install --upgrade pip
  & $py -m pip install -e ".[pipeline]"
}
if (-not (Test-Path "data\processed\segments.parquet")) {
  Write-Warning "Processed data not found - the app will start in MOCK DATA mode. See README (Quick start) to fetch or build the data."
}
$port = if ($env:PORT) { $env:PORT } else { "8000" }
Write-Host "Starting FloodEvac on http://localhost:$port  (first load takes about a minute while it reads live rain and river data)"
Start-Job -ScriptBlock { param($p) Start-Sleep -Seconds 40; Start-Process "http://localhost:$p" } -ArgumentList $port | Out-Null
& $py -m floodevac.api.app
