# Build the client release from the COMMITTED tree only (git archive), so untracked/ignored files such as
# .claude/ and .env can never be shipped. Also packs the large data/model artefacts as a separate zip for the
# GitHub Release assets.
#   .\scripts\make_release.ps1 -Version 1.0.0
param([string]$Version = "1.0.0")
$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
git rev-parse --is-inside-work-tree | Out-Null
if (git status --porcelain) { Write-Warning "Working tree has uncommitted changes; they are NOT included in the release." }

New-Item -ItemType Directory -Force dist | Out-Null
$src = "dist\floodevac-ernakulam-v$Version.zip"
git archive --format=zip --prefix="floodevac-ernakulam-v$Version/" -o $src HEAD
Write-Host "Source release: $src"

# guard: confidential files must not be in the archive
Add-Type -AssemblyName System.IO.Compression.FileSystem
$zip = [System.IO.Compression.ZipFile]::OpenRead((Resolve-Path $src))
$bad = $zip.Entries | Where-Object { $_.FullName -match '/\.claude/|/\.env$' }
$zip.Dispose()
if ($bad) { throw "Release contains confidential files: $($bad.FullName -join ', ')" }

# data + model artefacts (gitignored, attach to the GitHub Release)
$artefacts = "dist\floodevac-data-v$Version.zip"
$items = @("data\processed", "models", "qgis\floodevac.gpkg") | Where-Object { Test-Path $_ }
Compress-Archive -Path $items -DestinationPath $artefacts -Force
Write-Host "Data/model artefacts: $artefacts (attach to the GitHub Release)"
