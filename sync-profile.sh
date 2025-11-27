#!/bin/bash
# Sync Chrome/Chromium profile from local machine to Unraid server
# Run this on your LOCAL machine (Windows/Mac/Linux)

SERVER="root@192.168.1.216"
SERVER_PROFILE_DIR="/root/.config/chromium-takeout"
LOCAL_PROFILE_DIR=""

# Detect OS and set default Chrome profile location
if [[ "$OSTYPE" == "darwin"* ]]; then
    # macOS
    LOCAL_PROFILE_DIR="$HOME/Library/Application Support/Google/Chrome/Default"
elif [[ "$OSTYPE" == "linux-gnu"* ]]; then
    # Linux
    LOCAL_PROFILE_DIR="$HOME/.config/google-chrome/Default"
elif [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
    # Windows (Git Bash/Cygwin)
    LOCAL_PROFILE_DIR="$APPDATA/Google/Chrome/User Data/Default"
fi

# Allow override via command line
if [ -n "$1" ]; then
    LOCAL_PROFILE_DIR="$1"
fi

if [ ! -d "$LOCAL_PROFILE_DIR" ]; then
    echo "ERROR: Chrome profile not found at: $LOCAL_PROFILE_DIR"
    echo "Usage: $0 [path_to_chrome_profile]"
    echo ""
    echo "Common locations:"
    echo "  macOS:   ~/Library/Application Support/Google/Chrome/Default"
    echo "  Linux:   ~/.config/google-chrome/Default"
    echo "  Windows: %APPDATA%/Google/Chrome/User Data/Default"
    exit 1
fi

echo "[INFO] Syncing Chrome profile to server..."
echo "[INFO] Local:  $LOCAL_PROFILE_DIR"
echo "[INFO] Server: $SERVER:$SERVER_PROFILE_DIR"

# Create remote directory
ssh "$SERVER" "mkdir -p '$SERVER_PROFILE_DIR'"

# Sync only essential auth files
rsync -av --progress \
    --include 'Cookies' \
    --include 'Cookies-journal' \
    --include 'Login Data' \
    --include 'Login Data-journal' \
    --include 'Network/' \
    --include 'Network/Cookies' \
    --include 'Web Data' \
    --include 'Web Data-journal' \
    --include 'Local Storage/' \
    --include 'Local Storage/**' \
    --exclude '*' \
    "$LOCAL_PROFILE_DIR/" \
    "$SERVER:$SERVER_PROFILE_DIR/"

if [ $? -eq 0 ]; then
    echo ""
    echo "[SUCCESS] Profile synced successfully!"
    echo "[INFO] You can now run on the server:"
    echo "  BROWSER_PROFILE='$SERVER_PROFILE_DIR' python3 automated_takeout.py"
else
    echo "[ERROR] Profile sync failed!"
    exit 1
fi
