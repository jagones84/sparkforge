# SparkForge launcher (Windows) — mirrors run.sh: WebUI + API on http://127.0.0.1:8790
# Usage:   .\run.ps1 [--host 0.0.0.0] [any server.py argument]
# Blocked by policy?  powershell -ExecutionPolicy Bypass -File .\run.ps1
$ErrorActionPreference = "Stop"
Set-Location -Path $PSScriptRoot

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command py -ErrorAction SilentlyContinue }
if (-not $py) {
    Write-Error "Python 3 not found on PATH. Install it from https://www.python.org/downloads/windows/ (tick 'Add python.exe to PATH')."
    exit 127
}

& $py.Source (Join-Path $PSScriptRoot "server.py") @args
exit $LASTEXITCODE
