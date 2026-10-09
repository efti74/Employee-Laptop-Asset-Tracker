# Build OrgAssetAgent.exe standalone executable
$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$python = Join-Path $scriptDir ".venv\Scripts\python.exe"

if (-not (Test-Path $python)) {
    Write-Error "Virtual environment not found! Please run setup first."
    exit 1
}

Write-Host "Compiling OrgAssetAgent.exe with PyInstaller..." -ForegroundColor Cyan
& $python -m PyInstaller --clean --onefile --name OrgAssetAgent --noconfirm agent/agent.py

if ($LASTEXITCODE -eq 0) {
    Write-Host "`n[SUCCESS] Standalone executable created:" -ForegroundColor Green
    Write-Host "  - dist\OrgAssetAgent.exe" -ForegroundColor Green
} else {
    Write-Error "Build failed!"
}
