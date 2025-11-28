# Deploy Takeout Script to a remote Unraid server
# Usage: .\deploy.ps1 -RemoteHost <host> [-RemoteUser <user>] [-RemotePath <path>] [-Branch <branch>]
#
# Examples:
#   .\deploy.ps1 -RemoteHost 192.168.1.216
#   .\deploy.ps1 -RemoteHost 192.168.1.216 -RemoteUser root
#   .\deploy.ps1 -RemoteHost 192.168.1.216 -RemoteUser root -RemotePath /mnt/user/appdata/takeout-script
#   .\deploy.ps1 -RemoteHost 192.168.1.216 -Branch dev

[CmdletBinding()]
param(
    [Parameter(Mandatory=$true, Position=0, HelpMessage="IP address or hostname of the remote server")]
    [string]$RemoteHost,
    
    [Parameter(Mandatory=$false, Position=1, HelpMessage="SSH user (default: root)")]
    [string]$RemoteUser = "root",
    
    [Parameter(Mandatory=$false, Position=2, HelpMessage="Installation path on remote")]
    [string]$RemotePath = "/mnt/user/appdata/takeout-script",
    
    [Parameter(Mandatory=$false, Position=3, HelpMessage="Git branch to deploy (default: main)")]
    [string]$Branch = "main",
    
    [Parameter(Mandatory=$false, HelpMessage="Skip running the installer after clone")]
    [switch]$SkipInstall
)

$ErrorActionPreference = "Stop"

$GitRepo = "https://github.com/jeff-hamm/immich_takeout.git"

# Colors using Write-Host
function Write-Header($message) {
    Write-Host ""
    Write-Host "==========================================" -ForegroundColor Blue
    Write-Host $message -ForegroundColor Blue
    Write-Host "==========================================" -ForegroundColor Blue
    Write-Host ""
}

function Write-Success($message) {
    Write-Host "✓ $message" -ForegroundColor Green
}

function Write-Warn($message) {
    Write-Host "⚠ $message" -ForegroundColor Yellow
}

function Write-Err($message) {
    Write-Host "✗ $message" -ForegroundColor Red
}

function Write-Info($message) {
    Write-Host $message -ForegroundColor Cyan
}

Write-Header "Takeout Script Remote Deployment"

Write-Host "Remote Host: $RemoteUser@$RemoteHost"
Write-Host "Remote Path: $RemotePath"
Write-Host "Branch:      $Branch"
Write-Host "Repository:  $GitRepo"
Write-Host ""

# Check if ssh is available
if (-not (Get-Command ssh -ErrorAction SilentlyContinue)) {
    Write-Err "SSH client not found. Please install OpenSSH or use Windows 10+ with OpenSSH feature enabled."
    exit 1
}

# Test SSH connection
Write-Info "Testing SSH connection..."
try {
    $result = ssh -o ConnectTimeout=10 -o BatchMode=yes "$RemoteUser@$RemoteHost" "echo 'connected'" 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "SSH connection failed"
    }
    Write-Success "SSH connection successful"
}
catch {
    Write-Err "Cannot connect to $RemoteUser@$RemoteHost"
    Write-Host "Make sure:"
    Write-Host "  1. The remote host is reachable"
    Write-Host "  2. SSH is enabled on the remote host"
    Write-Host "  3. Your SSH key is authorized"
    exit 1
}

Write-Host ""

# Check/install git on remote
Write-Info "Checking git installation..."
$gitCheckScript = @'
if command -v git &> /dev/null; then
    echo "Git is already installed: $(git --version)"
else
    echo "Git not found, attempting to install..."
    if command -v apt-get &> /dev/null; then
        apt-get update && apt-get install -y git
    elif command -v yum &> /dev/null; then
        yum install -y git
    elif command -v apk &> /dev/null; then
        apk add git
    elif [ -f /etc/unraid-version ]; then
        echo "On Unraid - git should be pre-installed. Please install manually if missing."
        exit 1
    else
        echo "Could not determine package manager. Please install git manually."
        exit 1
    fi
fi
'@

ssh "$RemoteUser@$RemoteHost" "bash -c '$gitCheckScript'"
if ($LASTEXITCODE -ne 0) {
    Write-Err "Failed to ensure git is installed"
    exit 1
}
Write-Success "Git is available"
Write-Host ""

# Clone or update repository
Write-Info "Setting up repository..."

# Build the remote script with variables substituted
$cloneScript = @"
set -e
REMOTE_PATH='$RemotePath'
BRANCH='$Branch'
GIT_REPO='$GitRepo'

if [ -d "\`$REMOTE_PATH/.git" ]; then
    echo "Repository exists, pulling latest changes..."
    cd "\`$REMOTE_PATH"
    git fetch origin
    git checkout "\`$BRANCH"
    git pull origin "\`$BRANCH"
else
    echo "Cloning repository..."
    mkdir -p "\`$(dirname "\`$REMOTE_PATH")"
    if [ -d "\`$REMOTE_PATH" ] && [ "\`$(ls -A "\`$REMOTE_PATH" 2>/dev/null)" ]; then
        echo "Directory exists and is not empty. Backing up..."
        mv "\`$REMOTE_PATH" "\`${REMOTE_PATH}.backup.\`$(date +%Y%m%d_%H%M%S)"
    fi
    git clone --branch "\`$BRANCH" "\`$GIT_REPO" "\`$REMOTE_PATH"
fi

mkdir -p "\`$REMOTE_PATH/state"
echo "Repository ready at \`$REMOTE_PATH"
"@

ssh "$RemoteUser@$RemoteHost" "bash -c `"$cloneScript`""
if ($LASTEXITCODE -ne 0) {
    Write-Err "Failed to set up repository"
    exit 1
}
Write-Success "Repository ready"
Write-Host ""

# Set permissions
Write-Info "Setting permissions..."
ssh "$RemoteUser@$RemoteHost" "chmod +x '$RemotePath/install.sh' '$RemotePath/deploy.sh' '$RemotePath/sd-import/install.sh' 2>/dev/null || true"
Write-Success "Permissions set"
Write-Host ""

if (-not $SkipInstall) {
    Write-Header "Running installer on remote server..."
    
    # Run installer interactively
    ssh -t "$RemoteUser@$RemoteHost" "cd '$RemotePath' && sudo ./install.sh"
    
    Write-Host ""
    Write-Header "Deployment complete!"
}
else {
    Write-Warn "Skipping installer (use -SkipInstall:`$false to run)"
    Write-Host ""
    Write-Host "To run the installer manually:"
    Write-Host "  ssh $RemoteUser@$RemoteHost"
    Write-Host "  cd $RemotePath"
    Write-Host "  sudo ./install.sh"
}
