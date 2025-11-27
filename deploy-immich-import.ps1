param(
    [string]$Server = "192.168.1.216",
    [string]$User = "root",
    [string]$RemoteDir = "/mnt/user/appdata/takeout-script",
    [string]$ImmichUrl = "http://192.168.1.216:2283/api"
)

$ErrorActionPreference = "Stop"

function Invoke-Remote {
    param(
        [string]$Command
    )
    Write-Host "==> ssh $User@$Server $Command"
    ssh "$User@$Server" $Command
}

Write-Host "=== Step 1: Check Immich server status ==="
$immichStatus = Invoke-Remote "curl -s $ImmichUrl/server-info/ping 2>/dev/null || echo 'ERROR'"
if ($immichStatus -match "ERROR") {
    Write-Host "[WARNING] Could not reach Immich at $ImmichUrl"
    Write-Host "[INFO] Continuing with deployment anyway..."
}

Write-Host "=== Step 2: Create Immich API key ==="
Write-Host "[INFO] Checking for existing API key..."
$apiKeyCheck = Invoke-Remote "test -f /mnt/user/appdata/takeout-script/cache/.immich_api_key && cat /mnt/user/appdata/takeout-script/cache/.immich_api_key || echo 'NONE'"

if ($apiKeyCheck -eq "NONE") {
    Write-Host "[INFO] No existing API key found."
    Write-Host "[ACTION REQUIRED] Please create an API key manually:"
    Write-Host "  1. Go to http://192.168.1.216:2283"
    Write-Host "  2. Login and go to Account Settings > API Keys"
    Write-Host "  3. Create a new API key named 'takeout-importer'"
    Write-Host "  4. Save it to the server with:"
    Write-Host "     echo 'YOUR_API_KEY' > /mnt/user/appdata/takeout-script/cache/.immich_api_key"
    Write-Host ""
    $continue = Read-Host "Have you created and saved the API key? (y/N)"
    if ($continue -ne "y") {
        Write-Host "Exiting. Please create the API key and run this script again."
        exit 1
    }
}

Write-Host "=== Step 3: Copy files to remote ==="
$files = @("docker-compose.immich.yml", "Dockerfile.immich", "immich_import.py")
foreach ($f in $files) {
    $localPath = Join-Path $PSScriptRoot $f
    if (-not (Test-Path $localPath)) {
        throw "$f not found at $localPath"
    }
    $target = "${User}@${Server}:${RemoteDir}/$f"
    Write-Host "==> scp $localPath $target"
    scp $localPath $target
}

Write-Host "=== Step 4: Build immich-import Docker image ==="
Invoke-Remote "cd $RemoteDir && docker-compose -f docker-compose.immich.yml build"

Write-Host "=== Step 5: Start Immich import monitor ==="
Write-Host "[INFO] Starting immich-import container..."
Invoke-Remote "cd $RemoteDir && docker-compose -f docker-compose.immich.yml up -d"

Write-Host "=== Step 6: Check container status ==="
Start-Sleep -Seconds 3
Invoke-Remote "docker ps -a | grep immich-import"

Write-Host ""
Write-Host "=== Immich import deployment complete! ==="
Write-Host "The immich-import container is now monitoring for new Takeout zip files."
Write-Host "Check logs: docker logs -f immich-import"
Write-Host "Stop: docker-compose -f /mnt/user/appdata/takeout-script/docker-compose.immich.yml down"
