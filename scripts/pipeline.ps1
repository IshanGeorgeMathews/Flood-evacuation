# Run the full offline pipeline (Windows PowerShell). Cached steps are skipped; pass -Force to rebuild.
#   .\scripts\pipeline.ps1            # everything
#   .\scripts\pipeline.ps1 -Steps train,replay
param(
  [string[]]$Steps = @("all"),
  [switch]$Force
)
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
$py = Join-Path $root ".venv\Scripts\python.exe"
if (-not (Test-Path $py)) {
  Write-Host "Creating virtual environment..."
  python -m venv (Join-Path $root ".venv")
  & $py -m pip install --upgrade pip
  & $py -m pip install -e "$root[pipeline,dev]"
}
$extra = @()
if ($Force) { $extra += "--force" }
& $py -m floodevac.pipeline @Steps @extra
if ($LASTEXITCODE -ne 0) { throw "pipeline failed" }
& $py (Join-Path $root "scripts\snapshot_fixtures.py")
