#!/bin/bash
# Deploy Takeout Script to a remote Unraid server
# Usage: ./deploy.sh <remote_host> [remote_user] [remote_path] [branch]
#
# Examples:
#   ./deploy.sh 192.168.1.216
#   ./deploy.sh 192.168.1.216 root
#   ./deploy.sh 192.168.1.216 root $APP_PATH
#   ./deploy.sh 192.168.1.216 root $APP_PATH main

set -e

GIT_REPO="https://github.com/jeff-hamm/immich_takeout.git"

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_usage() {
    echo "Usage: $0 <remote_host> [remote_user] [remote_path] [branch]"
    echo ""
    echo "Arguments:"
    echo "  remote_host  - IP address or hostname of the remote server (required)"
    echo "  remote_user  - SSH user (default: root)"
    echo "  remote_path  - Installation path on remote (default: /mnt/user/appdata/takeout-script)"
    echo "  branch       - Git branch to deploy (default: main)"
    echo ""
    echo "Examples:"
    echo "  $0 192.168.1.216"
    echo "  $0 192.168.1.216 root"
    echo "  $0 192.168.1.216 root $APP_PATH"
    echo "  $0 192.168.1.216 root $APP_PATH dev"
}

if [ -z "$1" ]; then
    echo -e "${RED}Error: Remote host is required${NC}"
    echo ""
    print_usage
    exit 1
fi

REMOTE_HOST="$1"
REMOTE_USER="${2:-root}"
REMOTE_PATH="${3:-/mnt/user/appdata/takeout-script}"
BRANCH="${4:-main}"

echo -e "${BLUE}=========================================="
echo "Takeout Script Remote Deployment"
echo -e "==========================================${NC}"
echo ""
echo "Remote Host: $REMOTE_USER@$REMOTE_HOST"
echo "Remote Path: $REMOTE_PATH"
echo "Branch:      $BRANCH"
echo "Repository:  $GIT_REPO"
echo ""

# Test SSH connection
echo -e "${YELLOW}Testing SSH connection...${NC}"
if ! ssh -o ConnectTimeout=10 -o BatchMode=yes "$REMOTE_USER@$REMOTE_HOST" "echo 'SSH connection successful'" 2>/dev/null; then
    echo -e "${RED}Error: Cannot connect to $REMOTE_USER@$REMOTE_HOST${NC}"
    echo "Make sure:"
    echo "  1. The remote host is reachable"
    echo "  2. SSH is enabled on the remote host"
    echo "  3. Your SSH key is authorized (or use ssh-copy-id first)"
    exit 1
fi
echo -e "${GREEN}✓ SSH connection successful${NC}"
echo ""

# Check/install git on remote
echo -e "${YELLOW}Checking git installation...${NC}"
ssh "$REMOTE_USER@$REMOTE_HOST" bash << 'REMOTE_SCRIPT'
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
        # Unraid uses Slackware packages, git should be available
        echo "On Unraid - git should be pre-installed. Please install manually if missing."
        exit 1
    else
        echo "Could not determine package manager. Please install git manually."
        exit 1
    fi
fi
REMOTE_SCRIPT

if [ $? -ne 0 ]; then
    echo -e "${RED}Failed to ensure git is installed${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Git is available${NC}"
echo ""

# Clone or update repository
echo -e "${YELLOW}Setting up repository...${NC}"
ssh "$REMOTE_USER@$REMOTE_HOST" bash << REMOTE_SCRIPT
set -e
REMOTE_PATH="$REMOTE_PATH"
BRANCH="$BRANCH"
GIT_REPO="$GIT_REPO"

if [ -d "\$REMOTE_PATH/.git" ]; then
    echo "Repository exists, pulling latest changes..."
    cd "\$REMOTE_PATH"
    git fetch origin
    git checkout "\$BRANCH"
    git pull origin "\$BRANCH"
else
    echo "Cloning repository..."
    mkdir -p "\$(dirname "\$REMOTE_PATH")"
    if [ -d "\$REMOTE_PATH" ] && [ "\$(ls -A "\$REMOTE_PATH" 2>/dev/null)" ]; then
        echo "Directory exists and is not empty. Backing up..."
        mv "\$REMOTE_PATH" "\${REMOTE_PATH}.backup.\$(date +%Y%m%d_%H%M%S)"
    fi
    git clone --branch "\$BRANCH" "\$GIT_REPO" "\$REMOTE_PATH"
fi

# Create state directory if it doesn't exist
mkdir -p "\$REMOTE_PATH/state"

echo "Repository ready at \$REMOTE_PATH"
REMOTE_SCRIPT

if [ $? -ne 0 ]; then
    echo -e "${RED}Failed to set up repository${NC}"
    exit 1
fi
echo -e "${GREEN}✓ Repository ready${NC}"
echo ""

# Make install script executable
echo -e "${YELLOW}Setting permissions...${NC}"
ssh "$REMOTE_USER@$REMOTE_HOST" "chmod +x '$REMOTE_PATH/install.sh' '$REMOTE_PATH/deploy.sh' '$REMOTE_PATH/sd-import/install.sh' 2>/dev/null || true"
echo -e "${GREEN}✓ Permissions set${NC}"
echo ""

# Run installer
echo -e "${BLUE}=========================================="
echo "Running installer on remote server..."
echo -e "==========================================${NC}"
echo ""

ssh -t "$REMOTE_USER@$REMOTE_HOST" "cd '$REMOTE_PATH' && sudo ./install.sh"

echo ""
echo -e "${GREEN}=========================================="
echo "Deployment complete!"
echo -e "==========================================${NC}"
