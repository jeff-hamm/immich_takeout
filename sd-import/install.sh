#!/bin/bash
# SD Card Auto-Import Installer for Unraid
# This script installs the SD card auto-import system on a fresh Unraid system

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BOOT_CONFIG="/boot/config"

echo "=========================================="
echo "SD Card Auto-Import Installer for Unraid"
echo "=========================================="
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    echo "ERROR: This script must be run as root"
    exit 1
fi

# Ensure scripts are executable
echo "Setting script permissions..."
chmod +x "$SCRIPT_DIR/sd-card-import.sh"
chmod +x "$SCRIPT_DIR/immich-go-upload.sh"

# Download and install immich-go binary if not already present
if [ ! -f /usr/local/bin/immich-go ]; then
    echo "Downloading immich-go binary..."
    wget -q -O /tmp/immich-go.tar.gz https://github.com/simulot/immich-go/releases/latest/download/immich-go_Linux_x86_64.tar.gz
    tar -xzf /tmp/immich-go.tar.gz -C /tmp
    mv /tmp/immich-go /usr/local/bin/
    chmod +x /usr/local/bin/immich-go
    rm /tmp/immich-go.tar.gz
    echo "immich-go installed: $(immich-go version)"
else
    echo "immich-go already installed: $(immich-go version)"
fi

# Install to runtime locations via symlinks
echo "Creating symlinks in /usr/local/bin/..."
ln -sf "$SCRIPT_DIR/sd-card-import.sh" /usr/local/bin/sd-card-import.sh
ln -sf "$SCRIPT_DIR/immich-go-upload.sh" /usr/local/bin/immich-go-upload
ln -sf "$SCRIPT_DIR/../.env" /usr/local/bin/immich-go-upload.env

# Install udev rule
echo "Installing udev rule..."
cp "$SCRIPT_DIR/99-sd-card-import.rules" /etc/udev/rules.d/
udevadm control --reload-rules

# Backup existing go script if it exists
if [ -f "$BOOT_CONFIG/go" ]; then
    BACKUP_FILE="$BOOT_CONFIG/go.backup.$(date +%Y%m%d_%H%M%S)"
    echo "Backing up existing go script to: $BACKUP_FILE"
    cp "$BOOT_CONFIG/go" "$BACKUP_FILE"
else
    echo "Creating new go script..."
    cat > "$BOOT_CONFIG/go" << 'EOF'
#!/bin/bash
# Start the Management Utility
/usr/local/sbin/emhttp &
EOF
    chmod +x "$BOOT_CONFIG/go"
fi

# Source .env file to get configuration
ENV_FILE="$SCRIPT_DIR/../.env"
if [ -f "$ENV_FILE" ]; then
    echo "Loading configuration from .env file..."
    source <(grep -v '^#' "$ENV_FILE" | grep -v '^$' | sed 's/^/export /')
else
    echo "Warning: .env file not found at $ENV_FILE"
fi

# Check if go script already has our installation commands
if grep -q "sd-card-import.sh" "$BOOT_CONFIG/go"; then
    echo "SD card import is already in go script, skipping..."
else
    echo "Adding SD card import to go script..."
    cat >> "$BOOT_CONFIG/go" << EOF

# SD Card Auto-Import - create symlinks to persistent scripts
ln -sf "$SCRIPT_DIR/sd-card-import.sh" /usr/local/bin/sd-card-import.sh
ln -sf "$SCRIPT_DIR/immich-go-upload.sh" /usr/local/bin/immich-go-upload
ln -sf "$SCRIPT_DIR/../.env" /usr/local/bin/immich-go-upload.env
cp "$SCRIPT_DIR/99-sd-card-import.rules" /etc/udev/rules.d/
udevadm control --reload-rules

# Download and install immich-go binary if not already present
if [ ! -f /usr/local/bin/immich-go ]; then
    wget -q -O /tmp/immich-go.tar.gz https://github.com/simulot/immich-go/releases/latest/download/immich-go_Linux_x86_64.tar.gz
    tar -xzf /tmp/immich-go.tar.gz -C /tmp
    mv /tmp/immich-go /usr/local/bin/
    chmod +x /usr/local/bin/immich-go
    rm /tmp/immich-go.tar.gz
fi
EOF

    # Add environment variable exports if they exist
    if [ -n "$IMMICH_SERVER" ]; then
        echo "Adding IMMICH_SERVER configuration to go script..."
        cat >> "$BOOT_CONFIG/go" << EOF

# SD Card Import Configuration
export IMMICH_SERVER="$IMMICH_SERVER"
EOF
    fi
    
    # Check if API key file exists and add it
    API_KEY_FILE="$SCRIPT_DIR/../cache/.immich_api_key"
    if [ -f "$API_KEY_FILE" ]; then
        IMMICH_API_KEY=$(cat "$API_KEY_FILE" | tr -d '\n\r ')
        if [ -n "$IMMICH_API_KEY" ]; then
            echo "Adding IMMICH_API_KEY configuration to go script..."
            cat >> "$BOOT_CONFIG/go" << EOF
export IMMICH_API_KEY="$IMMICH_API_KEY"
EOF
        fi
    fi
fi

# Create import directory
echo "Creating import directory..."
mkdir -p /mnt/user/jumpdrive/imports

# Create log file
echo "Creating log file..."
touch /var/log/sd-card-import.log

echo ""
echo "=========================================="
echo "Installation Complete!"
echo "=========================================="
echo ""
echo "The SD card auto-import system has been installed."
echo ""
echo "Configuration:"
echo "  - Scripts: $SCRIPT_DIR (symlinked from /usr/local/bin)"
echo "  - Import directory: /mnt/user/jumpdrive/imports"
echo "  - Log file: /var/log/sd-card-import.log"
echo ""
echo "The system will automatically:"
echo "  1. Detect when an SD card matching the serial is inserted"
echo "  2. Copy all files from mountable partitions"
echo "  3. Track imported files to avoid re-importing"
echo "  4. Run immich-go to upload to Immich (if configured)"
echo ""
if [ -n "$IMMICH_SERVER" ]; then
    echo "Immich Configuration:"
    echo "  - Server: $IMMICH_SERVER"
    if [ -f "$API_KEY_FILE" ] && [ -n "$IMMICH_API_KEY" ]; then
        echo "  - API Key: ***configured***"
        echo ""
        echo "Environment variables have been added to $BOOT_CONFIG/go"
    else
        echo "  - API Key: NOT FOUND"
        echo ""
        echo "To enable Immich upload, add API key to:"
        echo "  $SCRIPT_DIR/../cache/.immich_api_key"
        echo "Or manually add to $BOOT_CONFIG/go:"
        echo "  export IMMICH_API_KEY=\"your-api-key-here\""
    fi
else
    echo "NEXT STEPS - Configure Immich Integration:"
    echo ""
    echo "1. Add configuration to: $SCRIPT_DIR/../.env"
    echo "   IMMICH_SERVER=http://192.168.1.216:2283"
    echo ""
    echo "2. Add API key to: $SCRIPT_DIR/../cache/.immich_api_key"
    echo ""
    echo "3. Re-run this installer or manually add to $BOOT_CONFIG/go:"
    echo "   export IMMICH_SERVER=\"http://192.168.1.216:2283\""
    echo "   export IMMICH_API_KEY=\"your-api-key-here\""
fi
echo ""
echo "Files will persist across reboots via the /boot/config directory."
echo ""
