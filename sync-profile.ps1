# Sync Chrome profile from Windows to Unraid server
# Run this in PowerShell on your LOCAL Windows machine

param(
    [string]$Server = "root@192.168.1.216",
    [string]$LocalProfile = "$env:LOCALAPPDATA\Google\Chrome\User Data\Default",
    [string]$ServerProfile = "/root/.config/chromium-takeout"
)

Write-Host "[INFO] Syncing Chrome profile to server..." -ForegroundColor Cyan
Write-Host "[INFO] Local:  $LocalProfile" -ForegroundColor Gray
Write-Host "[INFO] Server: ${Server}:${ServerProfile}" -ForegroundColor Gray

if (-not (Test-Path $LocalProfile)) {
    Write-Host "[ERROR] Chrome profile not found at: $LocalProfile" -ForegroundColor Red
    Write-Host "Common locations:" -ForegroundColor Yellow
    Write-Host "  $env:LOCALAPPDATA\Google\Chrome\User Data\Default" -ForegroundColor Yellow
    Write-Host "  $env:APPDATA\Google\Chrome\User Data\Default" -ForegroundColor Yellow
    exit 1
}

# Create remote directory
Write-Host "[INFO] Creating remote directory..." -ForegroundColor Cyan
ssh $Server "mkdir -p '$ServerProfile'"

# Use rsync via WSL or Git Bash, or scp as fallback
Write-Host "[INFO] Uploading profile files..." -ForegroundColor Cyan

# Copy only essential auth files
$authFiles = @(
    "Cookies",
    "Cookies-journal",
    "Login Data",
    "Login Data-journal",
    "Web Data",
    "Web Data-journal"
)

$authDirs = @(
    "Local Storage",
    "Network"
)

Write-Host "[INFO] Copying authentication files..." -ForegroundColor Cyan
foreach ($file in $authFiles) {
    $source = Join-Path $LocalProfile $file
    if (Test-Path $source) {
        Write-Host "  Copying $file..." -ForegroundColor Gray
        scp "$source" "${Server}:${ServerProfile}/"
    }
}

Write-Host "[INFO] Copying authentication directories..." -ForegroundColor Cyan
foreach ($dir in $authDirs) {
    $source = Join-Path $LocalProfile $dir
    if (Test-Path $source) {
        Write-Host "  Copying $dir/..." -ForegroundColor Gray
        scp -r "$source" "${Server}:${ServerProfile}/"
    }
}

if ($LASTEXITCODE -eq 0) {
    Write-Host ""
    Write-Host "[SUCCESS] Profile synced successfully!" -ForegroundColor Green
    Write-Host "[INFO] You can now run on the server:" -ForegroundColor Cyan
    Write-Host "  BROWSER_PROFILE='$ServerProfile' python3 automated_takeout.py" -ForegroundColor White
} else {
    Write-Host "[ERROR] Profile sync failed!" -ForegroundColor Red
    exit 1
}
