param(
    [string]$Server = "192.168.1.216",
    [string]$User = "root",
    [string]$RemoteDir = "/opt/takeout-script",
    [string]$PythonPath = "/usr/bin/python3"
)

$ErrorActionPreference = "Stop"

function Invoke-Remote {
    param(
        [string]$Command
    )
    Write-Host "==> ssh $User@$Server $Command"
    ssh "$User@$Server" $Command
}

Write-Host "=== Step 1: Ensure remote directory exists ==="
Invoke-Remote "mkdir -p $RemoteDir"

Write-Host "=== Step 2: Copy server_backup.py to remote ==="
$localScript = Join-Path $PSScriptRoot "server_backup.py"
if (-not (Test-Path $localScript)) {
    throw "server_backup.py not found at $localScript"
}

$scpTarget = "${User}@${Server}:${RemoteDir}/server_backup.py"
Write-Host "==> scp $localScript $scpTarget"
scp $localScript $scpTarget

Write-Host "=== Step 3: Install rclone and python3 (Debian/Ubuntu) ==="
Invoke-Remote "apt-get update && apt-get install -y rclone python3"

Write-Host "=== Step 4: Create backup root directory ==="
Invoke-Remote "mkdir -p /srv/backups/google-takeout"

Write-Host "=== Step 5: Test-run server_backup.py once ==="
Invoke-Remote "$PythonPath $RemoteDir/server_backup.py"

Write-Host "=== Deployment script finished ==="