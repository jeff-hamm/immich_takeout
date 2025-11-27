param(
    [string]$Server = "192.168.1.216",
    [string]$User = "root",
    [string]$RemoteDir = "/mnt/user/appdata/takeout-script"
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

Write-Host "=== Step 2: Copy Docker files to remote ==="
$files = @("Dockerfile", "docker-compose.yml", "server_backup.py")
foreach ($f in $files) {
    $localPath = Join-Path $PSScriptRoot $f
    if (-not (Test-Path $localPath)) {
        throw "$f not found at $localPath"
    }
    $target = "${User}@${Server}:${RemoteDir}/$f"
    Write-Host "==> scp $localPath $target"
    scp $localPath $target
}

Write-Host "=== Step 3: Ensure Docker and docker-compose are installed (manual step if missing) ==="
Write-Host "(Skipping automated Docker install to avoid OS-specific assumptions.)"

Write-Host "=== Step 4: Prepare backup and rclone directories on remote (Unraid paths) ==="
Invoke-Remote "mkdir -p /mnt/user/backups/google-takeout /mnt/user/appdata/rclone /mnt/user/appdata/takeout-script/logs"

Write-Host "=== Step 5: Build Docker image on remote ==="
Invoke-Remote "cd $RemoteDir && docker build -t takeout-backup:latest ."

Write-Host "=== Step 6: Run rclone config inside Docker if needed (manual) ==="
Write-Host "On the remote, run:"
Write-Host "  cd $RemoteDir"
Write-Host "  docker run --rm -it -v /srv/backups/google-takeout/rclone:/config/rclone --entrypoint rclone takeout-backup:latest config"

Write-Host "=== Step 7: Test one-off backup container run ==="
Invoke-Remote "cd $RemoteDir && docker run --rm -v /mnt/user/backups/google-takeout:/mnt/user/backups/google-takeout -v /mnt/user/appdata/rclone:/config/rclone takeout-backup:latest" 

Write-Host "=== Step 8: Bring up with docker-compose (one-shot run) ==="
Invoke-Remote "cd $RemoteDir && docker-compose up --no-start && docker-compose run --rm takeout-backup"

Write-Host "=== Docker deployment script finished ==="