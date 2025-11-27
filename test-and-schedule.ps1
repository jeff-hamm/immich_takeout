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

Write-Host "=== Testing backup script with Docker ==="
$testCommand = "cd $RemoteDir && docker run --rm -v /mnt/user/backups/google-takeout:/mnt/user/backups/google-takeout -v /mnt/user/appdata/rclone:/config/rclone takeout-backup:latest"
Write-Host "==> ssh $User@$Server `"$testCommand`""
ssh "$User@$Server" $testCommand

Write-Host ""
Write-Host "=== Checking backup results ==="
Invoke-Remote "ls -lh /mnt/user/backups/google-takeout/raw"
Invoke-Remote "ls -lh /mnt/user/backups/google-takeout/extracted"
Invoke-Remote "cat /mnt/user/backups/google-takeout/state/processed_files.txt"

Write-Host ""
Write-Host "=== Setting up cron job ==="
$cronLine = "30 3 * * * cd /mnt/user/appdata/takeout-script && docker run --rm -v /mnt/user/backups/google-takeout:/mnt/user/backups/google-takeout -v /mnt/user/appdata/rclone:/config/rclone takeout-backup:latest >> /mnt/user/appdata/takeout-script/logs/takeout-backup.log 2>&1"
$cronSetup = "(crontab -l 2>/dev/null | grep -v 'takeout-backup'; echo '$cronLine') | crontab -"
Write-Host "==> ssh $User@$Server `"$cronSetup`""
ssh "$User@$Server" $cronSetup

Write-Host ""
Write-Host "=== Verifying cron job ==="
Invoke-Remote "crontab -l | grep takeout"

Write-Host ""
Write-Host "=== Deployment complete! ==="
Write-Host "Backup will run daily at 3:30 AM server time."
Write-Host "Logs will be written to /mnt/cache/appdata/takeout-script/logs/takeout-backup.log on the server."
