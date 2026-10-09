# Start Streamlit Admin Dashboard
param(
    [int]$Port = 8501
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$streamlit = Join-Path $scriptDir ".venv\Scripts\streamlit.exe"

if (-not (Test-Path $streamlit)) {
    Write-Error "Virtual environment not found! Please run 'python -m venv .venv' and install requirements."
    exit 1
}

Write-Host "Starting Streamlit Dashboard on port $Port ..." -ForegroundColor Cyan
& $streamlit run dashboard/app.py --server.port $Port
