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

Write-Host "=== Configuring rclone for Google Drive ==="
Write-Host "This will open an interactive rclone config session."
Write-Host "Please follow the prompts to:"
Write-Host "  1. Create a new remote (press 'n')"
Write-Host "  2. Name it 'gdrive'"
Write-Host "  3. Choose 'drive' for Google Drive"
Write-Host "  4. Complete the OAuth flow in your browser"
Write-Host ""

$configCommand = "cd $RemoteDir && docker run --rm -it -v /mnt/user/appdata/rclone:/config/rclone --entrypoint rclone takeout-backup:latest config"
Write-Host "==> ssh -t $User@$Server `"$configCommand`""
ssh -t "$User@$Server" $configCommand

Write-Host ""
Write-Host "=== Verifying rclone configuration ==="
$verifyCommand = "cd $RemoteDir && docker run --rm -v /mnt/user/appdata/rclone:/config/rclone --entrypoint rclone takeout-backup:latest lsd gdrive:"
Write-Host "==> ssh $User@$Server `"$verifyCommand`""
ssh "$User@$Server" $verifyCommand

Write-Host ""
Write-Host "=== rclone configuration complete ==="
