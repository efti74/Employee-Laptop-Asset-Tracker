# Helper script to enroll a device in the Asset Tracker
param(
    [string]$Hostname = $env:COMPUTERNAME,
    [string]$AssetTag = "ASSET-$((Get-Random -Minimum 1000 -Maximum 9999))",
    [string]$ApiUrl = "http://127.0.0.1:8000",
    [string]$AdminToken = $env:ADMIN_TOKEN,
    [switch]$SaveToLocalConfig
)

if (-not $AdminToken) {
    Write-Host "Enter your ADMIN_TOKEN:" -ForegroundColor Yellow
    $AdminToken = Read-Host
}

if (-not $AdminToken) {
    Write-Error "Admin token is required to enroll a device."
    exit 1
}

$headers = @{ "Authorization" = "Bearer $AdminToken" }
$body = @{
    hostname = $Hostname
    asset_tag = $AssetTag
} | ConvertTo-Json

try {
    Write-Host "Enrolling device: Hostname=$Hostname, AssetTag=$AssetTag ..." -ForegroundColor Cyan
    $response = Invoke-RestMethod -Method Post -Uri "$ApiUrl/admin/enroll" -Headers $headers -ContentType "application/json" -Body $body
    Write-Host "Device enrolled successfully!" -ForegroundColor Green
    $response | Format-List

    if ($SaveToLocalConfig) {
        $config = @{
            api_base_url = $ApiUrl
            device_id = $response.device_id
            device_token = $response.device_token
        } | ConvertTo-Json
        $configPath = Join-Path $PSScriptRoot "agent\device_config.json"
        Set-Content -Path $configPath -Value $config -Encoding UTF8
        Write-Host "Saved device config to $configPath" -ForegroundColor Green
    }
} catch {
    Write-Error "Failed to enroll device: $_"
}
