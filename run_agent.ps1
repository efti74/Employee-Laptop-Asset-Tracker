# Run Windows Location Agent
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$python = Join-Path $scriptDir ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "Virtual environment not found! Please run 'python -m venv .venv' and install requirements."
    exit 1
}

Write-Host "Starting Windows Asset Tracker Agent ..." -ForegroundColor Cyan
& $python agent/agent.py
