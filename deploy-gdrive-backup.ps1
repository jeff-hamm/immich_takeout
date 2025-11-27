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

Write-Host "=== Step 2: Copy Google Drive backup Docker files to remote ==="
$files = @("Dockerfile.gdrive", "docker-compose.gdrive.yml", "gdrive_backup.py")
foreach ($f in $files) {
    $localPath = Join-Path $PSScriptRoot $f
    if (-not (Test-Path $localPath)) {
        throw "$f not found at $localPath"
    }
    $target = "${User}@${Server}:${RemoteDir}/$f"
    Write-Host "==> scp $localPath $target"
    scp $localPath $target
}

Write-Host "=== Step 3: Prepare Google Drive backup directory on remote (Unraid paths) ==="
Invoke-Remote "mkdir -p /mnt/user/backups/google-drive /mnt/cache/appdata/takeout-script/logs"

Write-Host "=== Step 4: Build Google Drive Docker image on remote ==="
Invoke-Remote "cd $RemoteDir && docker build -f Dockerfile.gdrive -t gdrive-backup:latest ."

Write-Host "=== Step 5: Test one-off Google Drive backup container run ==="
Invoke-Remote "cd $RemoteDir && docker run --rm -v /mnt/user/jumpdrive/gdrive:/mnt/user/jumpdrive/gdrive -v /mnt/user/appdata/rclone:/config/rclone gdrive-backup:latest"

Write-Host "=== Step 6: Set up cron job for daily Google Drive backup ==="
$cronLine = "0 4 * * * cd /mnt/cache/appdata/takeout-script && docker run --rm -v /mnt/user/backups/google-drive:/mnt/user/backups/google-drive -v /mnt/user/appdata/rclone:/config/rclone gdrive-backup:latest >> /mnt/cache/appdata/takeout-script/logs/gdrive-backup.log 2>&1"
$cronSetup = "(crontab -l 2>/dev/null | grep -v 'gdrive-backup'; echo '$cronLine') | crontab -"
Write-Host "==> ssh $User@$Server `"$cronSetup`""
ssh "$User@$Server" $cronSetup

Write-Host ""
Write-Host "=== Step 7: Verify cron jobs ==="
Invoke-Remote "crontab -l | grep backup"

Write-Host ""
Write-Host "=== Google Drive backup deployment complete! ==="
Write-Host "Takeout backup: Daily at 3:30 AM -> /mnt/cache/appdata/takeout-script/logs/takeout-backup.log"
Write-Host "Google Drive backup: Daily at 4:00 AM -> /mnt/cache/appdata/takeout-script/logs/gdrive-backup.log"
