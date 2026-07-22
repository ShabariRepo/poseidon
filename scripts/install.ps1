# Poseidon installer for Windows — run in PowerShell:
#   irm https://raw.githubusercontent.com/ShabariRepo/poseidon/main/scripts/install.ps1 | iex
$ErrorActionPreference = "Stop"
$py = (Get-Command python -ErrorAction SilentlyContinue) ?? (Get-Command python3 -ErrorAction SilentlyContinue)
if (-not $py) { Write-Host "Poseidon needs Python 3.10+ — install it from https://python.org (check 'Add to PATH'), then re-run." ; exit 1 }
$ok = & $py.Source -c "import sys; print(1 if sys.version_info >= (3,10) else 0)"
if ($ok.Trim() -ne "1") { Write-Host "Poseidon needs Python 3.10+ — yours is older. Update from https://python.org." ; exit 1 }
$dir = "$env:USERPROFILE\.poseidon-app"
if (-not (Test-Path "$dir\venv")) { & $py.Source -m venv "$dir\venv" }
Write-Host "Installing Poseidon..."
& "$dir\venv\Scripts\pip.exe" install -q --upgrade pip poseidon-ai
Write-Host "Poseidon installed. Starting..."
& "$dir\venv\Scripts\poseidon.exe"
