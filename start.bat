@echo off
rem Double-click to start FloodEvac Ernakulam (opens http://localhost:8000 when ready).
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
pause
