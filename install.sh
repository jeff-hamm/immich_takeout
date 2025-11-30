#!/bin/bash
# Takeout Script Full Installation Script
# Interactive installer for the complete Google Photos backup system
# Idempotent: safe to run multiple times - will detect existing config and prompt

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="$SCRIPT_DIR/.env"
STATE_DIR="$SCRIPT_DIR/state"

# Default appdata root (can be overridden by .env)
APP_ROOT="/mnt/user/appdata"
RCLONE_CONFIG_DIR="$APP_ROOT/rclone"
CHADBURN_COMPOSE_DIR="$APP_ROOT/chadburn"

# Application name (used in API key names, comments, etc.)
APP_NAME="takeout-script"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Helper functions
print_header() {
    echo ""
    echo -e "${BLUE}=========================================="
    echo "$1"
    echo -e "==========================================${NC}"
    echo ""
}

print_success() {
    echo -e "${GREEN}✓ $1${NC}"
}

print_warning() {
    echo -e "${YELLOW}⚠ $1${NC}"
}

print_error() {
    echo -e "${RED}✗ $1${NC}"
}

prompt_with_default() {
    local prompt="$1"
    local default="$2"
    local var_name="$3"
    local is_password="${4:-false}"
    
    if [ "$is_password" = "true" ]; then
        echo -n "$prompt [$default]: "
        read -s value
        echo ""
    else
        read -p "$prompt [$default]: " value
    fi
    
    if [ -z "$value" ]; then
        value="$default"
    fi
    
    eval "$var_name='$value'"
}

prompt_required() {
    local prompt="$1"
    local var_name="$2"
    local is_password="${3:-false}"
    local value=""
    
    while [ -z "$value" ]; do
        if [ "$is_password" = "true" ]; then
            echo -n "$prompt: "
            read -s value
            echo ""
        else
            read -p "$prompt: " value
        fi
        
        if [ -z "$value" ]; then
            print_error "This field is required"
        fi
    done
    
    eval "$var_name='$value'"
}

confirm() {
    local prompt="$1"
    local default="${2:-y}"
    local yn_hint="Y/n"
    [ "$default" = "n" ] && yn_hint="y/N"
    
    read -p "$prompt [$yn_hint]: " response
    response="${response:-$default}"
    
    case "$response" in
        [yY][eE][sS]|[yY]) return 0 ;;
        *) return 1 ;;
    esac
}

# Get current machine IP
get_current_ip() {
    # Try multiple methods to get the IP
    local ip=""
    
    # Method 1: hostname -I
    ip=$(hostname -I 2>/dev/null | awk '{print $1}')
    
    # Method 2: ip route
    if [ -z "$ip" ]; then
        ip=$(ip route get 1 2>/dev/null | awk '{print $7; exit}')
    fi
    
    # Method 3: ifconfig
    if [ -z "$ip" ]; then
        ip=$(ifconfig 2>/dev/null | grep -Eo 'inet (addr:)?([0-9]*\.){3}[0-9]*' | grep -Eo '([0-9]*\.){3}[0-9]*' | grep -v '127.0.0.1' | head -1)
    fi
    
    echo "$ip"
}

# Generate a random password
generate_password() {
    local length="${1:-16}"
    tr -dc 'A-Za-z0-9!@#$%^&*' </dev/urandom | head -c "$length"
}

print_header "Takeout Script Full Installation"

echo "This script will set up the complete Google Photos backup system including:"
echo "  1. Environment configuration (.env file)"
echo "  2. rclone configuration for Google Drive"
echo "  3. Chadburn scheduler (if not running)"
echo "  4. Immich API key generation"
echo "  5. SD Card auto-import (optional)"
echo "  6. Docker services"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    print_error "This script must be run as root"
    exit 1
fi

# Get current user info for docker
CURRENT_USER="${SUDO_USER:-$USER}"
CURRENT_UID=$(id -u "$CURRENT_USER" 2>/dev/null || echo "0")
CURRENT_GID=$(id -g "$CURRENT_USER" 2>/dev/null || echo "0")

print_header "Step 1: Environment Configuration"

# Detect current IP
DETECTED_IP=$(get_current_ip)
if [ -z "$DETECTED_IP" ]; then
    DETECTED_IP="192.168.1.216"
fi

echo "Detected server IP: $DETECTED_IP"
echo ""

# Load existing .env if present
if [ -f "$ENV_FILE" ]; then
    print_warning "Existing .env file found. Loading current values..."
    source <(grep -v '^#' "$ENV_FILE" | grep -v '^$' | sed 's/^/export /')
fi

# Prompt for configuration
prompt_with_default "Server IP address" "${SERVER_IP:-$DETECTED_IP}" "SERVER_IP"
prompt_with_default "Immich server URL" "${IMMICH_SERVER:-http://$SERVER_IP:2283}" "IMMICH_SERVER"

# Generate default VNC password if not set
DEFAULT_VNC_PASSWORD="${VNC_PASSWORD:-$(generate_password 16)}"
prompt_with_default "VNC password for login-helper" "$DEFAULT_VNC_PASSWORD" "VNC_PASSWORD" "true"

prompt_with_default "Google Drive path" "${GDRIVE_PATH:-/mnt/user/jumpdrive/gdrive}" "GDRIVE_PATH"
prompt_with_default "Imports path" "${IMPORTS_PATH:-/mnt/user/jumpdrive/imports}" "IMPORTS_PATH"
prompt_with_default "rclone config path" "${RCLONE_CONFIG:-/mnt/user/appdata/rclone/rclone.conf}" "RCLONE_CONFIG"
prompt_with_default "State path" "${STATE_PATH:-./state}" "STATE_PATH"
prompt_with_default "kasmweb version" "${kasmweb_version:-1.18.0}" "kasmweb_version"

# Create directories
echo ""
echo "Creating directories..."
mkdir -p "$GDRIVE_PATH"
mkdir -p "$IMPORTS_PATH"
mkdir -p "$IMPORTS_PATH/metadata"
mkdir -p "$(dirname "$RCLONE_CONFIG")"
mkdir -p "$STATE_DIR"
print_success "Directories created"

# Write .env file
echo ""
echo "Writing .env file..."
cat > "$ENV_FILE" << EOF
# Takeout Script Configuration
# Generated by install.sh on $(date)

# Server Configuration
SERVER_IP=$SERVER_IP
IMMICH_SERVER=$IMMICH_SERVER
VNC_PASSWORD='$VNC_PASSWORD'

# Storage Paths
GDRIVE_PATH=$GDRIVE_PATH
IMPORTS_PATH=$IMPORTS_PATH
STATE_PATH=$STATE_PATH

# rclone Configuration
RCLONE_CONFIG=$RCLONE_CONFIG
RCLONE_REMOTE=gdrive:
RCLONE_TAKEOUT_PATH=gdrive:Takeout

# Docker Image Versions
kasmweb_version=$kasmweb_version

# Optional: Google password for automated login (leave empty to skip)
GOOGLE_PASSWORD=
EOF

print_success ".env file written to $ENV_FILE"

print_header "Step 2: rclone Configuration for Google Drive"

RCLONE_CONFIG_DIR=$(dirname "$RCLONE_CONFIG")
mkdir -p "$RCLONE_CONFIG_DIR"

if [ -f "$RCLONE_CONFIG" ] && grep -q "\[gdrive\]" "$RCLONE_CONFIG" 2>/dev/null; then
    print_warning "rclone gdrive remote already configured"
    if ! confirm "Reconfigure rclone gdrive remote?" "n"; then
        echo "Skipping rclone configuration..."
    else
        CONFIGURE_RCLONE=true
    fi
else
    CONFIGURE_RCLONE=true
fi

if [ "$CONFIGURE_RCLONE" = "true" ]; then
    echo ""
    echo "To configure Google Drive access, you need to create OAuth credentials:"
    echo ""
    echo "1. Go to: https://console.cloud.google.com/apis/credentials"
    echo "2. Create a new OAuth 2.0 Client ID (Desktop application)"
    echo "3. Download or note the Client ID and Client Secret"
    echo ""
    
    if confirm "Do you have your Google OAuth credentials ready?" "y"; then
        prompt_required "Enter Google OAuth Client ID" "RCLONE_CLIENT_ID"
        prompt_required "Enter Google OAuth Client Secret" "RCLONE_CLIENT_SECRET" "true"
        
        echo ""
        echo "Now we need to authorize rclone with your Google account."
        echo "This will open a browser or provide a URL for authorization."
        echo ""
        
        # Check if rclone is installed
        if ! command -v rclone &> /dev/null; then
            echo "Installing rclone..."
            curl -s https://rclone.org/install.sh | bash
        fi
        
        # Create initial config
        cat > "$RCLONE_CONFIG" << EOF
[gdrive]
type = drive
client_id = $RCLONE_CLIENT_ID
client_secret = $RCLONE_CLIENT_SECRET
scope = drive
EOF
        
        echo ""
        echo "Running rclone authorization..."
        echo "Please follow the prompts to authorize access to your Google Drive."
        echo ""
        
        # Run rclone config reconnect to get the token
        rclone config reconnect gdrive: --config "$RCLONE_CONFIG"
        
        if [ $? -eq 0 ]; then
            print_success "rclone configured successfully"
        else
            print_error "rclone configuration failed"
            echo "You can manually run: rclone config --config $RCLONE_CONFIG"
        fi
    else
        print_warning "Skipping rclone configuration"
        echo "You can manually configure rclone later with:"
        echo "  rclone config --config $RCLONE_CONFIG"
    fi
fi

print_header "Step 3: Chadburn Scheduler Setup"

# Check if chadburn is already running
CHADBURN_RUNNING=$(docker ps --filter "name=chadburn" --format "{{.Names}}" 2>/dev/null || true)
CHADBURN_EXISTS=$(docker ps -a --filter "name=chadburn" --format "{{.Names}}" 2>/dev/null || true)

if [ -n "$CHADBURN_RUNNING" ]; then
    print_success "Chadburn is already running"
elif [ -n "$CHADBURN_EXISTS" ]; then
    print_warning "Chadburn container exists but is not running"
    if confirm "Start Chadburn?" "y"; then
        docker start chadburn
        print_success "Chadburn started"
    fi
else
    print_warning "Chadburn is not installed"
    
    if confirm "Install and start Chadburn scheduler?" "y"; then
        mkdir -p "$CHADBURN_COMPOSE_DIR"
        
        # Write compose file (idempotent - overwrites if exists)
        cat > "$CHADBURN_COMPOSE_DIR/docker-compose.yml" << EOF
# Chadburn - Docker-native cron scheduler
# Generated by $APP_NAME install.sh on $(date)

services:
  chadburn:
    image: premoweb/chadburn:latest
    container_name: chadburn
    user: "${CURRENT_UID}:${CURRENT_GID}"
    restart: unless-stopped
    command: daemon
    volumes:
      - /var/run/docker.sock:/var/run/docker.sock:ro
    network_mode: bridge
    labels:
      - "net.unraid.docker.managed=composeman"
EOF
        
        echo "Starting Chadburn..."
        cd "$CHADBURN_COMPOSE_DIR"
        docker compose up -d
        
        if [ $? -eq 0 ]; then
            print_success "Chadburn started successfully"
        else
            print_error "Failed to start Chadburn"
        fi
        
        cd "$SCRIPT_DIR"
    else
        print_warning "Skipping Chadburn installation"
        echo "Note: Scheduled tasks will not run without Chadburn"
    fi
fi

print_header "Step 4: Immich API Key Configuration"

API_KEY_FILE="$STATE_DIR/.immich_api_key"

if [ -f "$API_KEY_FILE" ] && [ -s "$API_KEY_FILE" ]; then
    print_warning "Immich API key already exists"
    if ! confirm "Generate a new API key?" "n"; then
        echo "Keeping existing API key..."
        SKIP_API_KEY=true
    fi
fi

if [ "$SKIP_API_KEY" != "true" ]; then
    echo "Checking Immich server connectivity..."
    
    # Test connection to Immich
    if curl -s --connect-timeout 5 "$IMMICH_SERVER/api/server/ping" | grep -q "pong"; then
        print_success "Immich server is reachable"
        
        echo ""
        echo "To generate an API key, we need to authenticate with Immich."
        echo ""
        
        prompt_required "Enter Immich admin email" "IMMICH_EMAIL"
        prompt_required "Enter Immich admin password" "IMMICH_PASSWORD" "true"
        
        echo ""
        echo "Authenticating with Immich..."
        
        # Login to get access token
        LOGIN_RESPONSE=$(curl -s -X POST "$IMMICH_SERVER/api/auth/login" \
            -H "Content-Type: application/json" \
            -d "{\"email\": \"$IMMICH_EMAIL\", \"password\": \"$IMMICH_PASSWORD\"}")
        
        ACCESS_TOKEN=$(echo "$LOGIN_RESPONSE" | grep -o '"accessToken":"[^"]*"' | cut -d'"' -f4)
        
        if [ -n "$ACCESS_TOKEN" ]; then
            print_success "Authentication successful"
            
            # Create API key
            echo "Creating API key..."
            
            API_KEY_RESPONSE=$(curl -s -X POST "$IMMICH_SERVER/api/api-keys" \
                -H "Content-Type: application/json" \
                -H "Authorization: Bearer $ACCESS_TOKEN" \
                -d "{\"name\": \"$APP_NAME\"}")
            
            API_KEY=$(echo "$API_KEY_RESPONSE" | grep -o '"secret":"[^"]*"' | cut -d'"' -f4)
            
            if [ -n "$API_KEY" ]; then
                echo "$API_KEY" > "$API_KEY_FILE"
                chmod 600 "$API_KEY_FILE"
                print_success "API key generated and saved to $API_KEY_FILE"
            else
                print_error "Failed to create API key"
                echo "Response: $API_KEY_RESPONSE"
                echo ""
                echo "You can manually create an API key in Immich:"
                echo "1. Go to $IMMICH_SERVER/user-settings?isOpen=api-keys"
                echo "2. Create a new API key"
                echo "3. Save it to: $API_KEY_FILE"
            fi
        else
            print_error "Authentication failed"
            echo "Response: $LOGIN_RESPONSE"
            echo ""
            echo "You can manually create an API key in Immich:"
            echo "1. Go to $IMMICH_SERVER/user-settings?isOpen=api-keys"
            echo "2. Create a new API key"
            echo "3. Save it to: $API_KEY_FILE"
        fi
    else
        print_warning "Cannot reach Immich server at $IMMICH_SERVER"
        echo "Make sure Immich is running and try again, or manually configure later."
        echo ""
        echo "To manually configure:"
        echo "1. Create an API key in Immich user settings"
        echo "2. Save it to: $API_KEY_FILE"
    fi
fi

print_header "Step 5: SD Card Auto-Import (Optional)"

echo "SD card auto-import can automatically import photos when an SD card is inserted."
echo "To find your SD card reader's serial, insert a card and run:"
echo "  udevadm info --query=all --name=/dev/sdb | grep ID_SERIAL="
echo ""

# Check for existing SD reader configuration
SD_RULES_FILE="$SCRIPT_DIR/sd-import/99-sd-card-import.rules"
EXISTING_SD_READER=""
if [ -f "$SD_RULES_FILE" ]; then
    EXISTING_SD_READER=$(grep -oP 'ID_SERIAL==\"\K[^\"]+' "$SD_RULES_FILE" 2>/dev/null | head -1)
fi

if [ -n "$EXISTING_SD_READER" ]; then
    echo "Current SD reader: $EXISTING_SD_READER"
fi

read -p "Enter SD card reader serial (leave empty to skip SD import): " SD_READER_SERIAL

if [ -n "$SD_READER_SERIAL" ]; then
    # Update the udev rules file with the new serial
    cat > "$SD_RULES_FILE" << EOF
# Unraid SD Card Auto-Import Rule
# Triggers import script when SD card reader detects media
# Device: $SD_READER_SERIAL

ACTION=="add", SUBSYSTEM=="block", ENV{DEVTYPE}=="disk", \\
  ENV{ID_SERIAL}=="$SD_READER_SERIAL", \\
  RUN+="/usr/bin/at -M now", ENV{SYSTEMD_WANTS}="", \\
  RUN+="/bin/sh -c 'echo \"/usr/local/bin/sd-card-import.sh %k\" | /usr/bin/at -M now'"

ACTION=="remove", SUBSYSTEM=="block", ENV{DEVTYPE}=="disk", \\
  ENV{ID_SERIAL}=="$SD_READER_SERIAL", \\
  RUN+="/bin/bash -c 'for mp in /mnt/sd-import/*; do [ -d \"\$mp\" ] && umount \"\$mp\" 2>/dev/null && rmdir \"\$mp\"; done; rmdir /mnt/sd-import 2>/dev/null || true'"
EOF
    print_success "Updated udev rules for SD reader: $SD_READER_SERIAL"
    
    echo "Running SD card import installer..."
    bash "$SCRIPT_DIR/sd-import/install.sh"
else
    print_warning "Skipping SD card auto-import installation (no reader specified)"
fi

print_header "Step 6: GitHub Copilot CLI Authentication (Optional)"

COPILOT_TOKEN_FILE="$STATE_DIR/.copilot-token"

echo "The vscode-monitor service uses GitHub Copilot CLI to auto-fix Playwright scripts."
echo "This requires a GitHub Personal Access Token (PAT) with 'Copilot Requests' permission."
echo ""

if [ -f "$COPILOT_TOKEN_FILE" ] && [ -s "$COPILOT_TOKEN_FILE" ]; then
    print_warning "Copilot token already exists at $COPILOT_TOKEN_FILE"
    if ! confirm "Replace existing Copilot token?" "n"; then
        echo "Keeping existing token..."
        SKIP_COPILOT=true
    fi
fi

if [ "$SKIP_COPILOT" != "true" ]; then
    if confirm "Configure GitHub Copilot CLI authentication?" "y"; then
        echo ""
        echo "To create a token with Copilot access:"
        echo "1. Go to: https://github.com/settings/personal-access-tokens/new"
        echo "2. Give it a name like '$APP_NAME-copilot'"
        echo "3. Under 'Permissions', click 'Account permissions'"
        echo "4. Find 'Copilot' and set it to 'Read-only'"
        echo "5. Generate and copy the token"
        echo ""
        
        prompt_required "Paste your GitHub PAT with Copilot permission" "COPILOT_TOKEN" "true"
        
        # Save the token
        echo "$COPILOT_TOKEN" > "$COPILOT_TOKEN_FILE"
        chmod 600 "$COPILOT_TOKEN_FILE"
        print_success "Copilot token saved to $COPILOT_TOKEN_FILE"
        
        # Create symlink for root access (persists via go file on reboot)
        ln -sf "$COPILOT_TOKEN_FILE" /root/.copilot-token
        print_success "Created symlink /root/.copilot-token -> $COPILOT_TOKEN_FILE"
    else
        print_warning "Skipping Copilot authentication"
        echo "The vscode-monitor service will not be able to auto-fix scripts."
        echo "You can configure it later by creating: $COPILOT_TOKEN_FILE"
    fi
fi

print_header "Step 7: Unraid Shell Customizations"

echo "Installing shell customizations for Unraid persistence..."

UNRAID_SCRIPTS_DIR="/boot/config/custom-scripts"
mkdir -p "$UNRAID_SCRIPTS_DIR"

# Install custom bashrc with docker aliases
if [ -f "$SCRIPT_DIR/unraid/bashrc" ]; then
    cp "$SCRIPT_DIR/unraid/bashrc" "$UNRAID_SCRIPTS_DIR/bashrc"
    cp "$UNRAID_SCRIPTS_DIR/bashrc" /root/.bashrc
    print_success "Installed custom bashrc with docker aliases (d, dc, dcr, etc.)"
else
    print_warning "unraid/bashrc not found, skipping"
fi

# Install go file (boot script)
if [ -f "$SCRIPT_DIR/unraid/go" ]; then
    # Get API key if available
    API_KEY=""
    if [ -f "$API_KEY_FILE" ] && [ -s "$API_KEY_FILE" ]; then
        API_KEY=$(cat "$API_KEY_FILE")
    fi
    
    # Replace placeholder with actual API key and install
    sed "s/__IMMICH_API_KEY__/$API_KEY/" "$SCRIPT_DIR/unraid/go" > /boot/config/go
    chmod +x /boot/config/go
    print_success "Installed Unraid boot script (/boot/config/go)"
    
    # Apply profile fix immediately
    sed -i '/^cd \$HOME$/d' /etc/profile
    print_success "Applied profile fix (removed cd \$HOME)"
    
    # Apply /var/log resize immediately (don't wait for reboot)
    mount -o remount,size=1G /var/log 2>/dev/null || true
    print_success "Increased /var/log to 1GB"
    
    # Install array control scripts immediately
    cat > /usr/local/bin/array-stop << 'ARRAY_EOF'
#!/bin/bash
echo "Stopping array..."
/usr/local/sbin/emcmd cmdStop=Stop
echo "Waiting for array to stop..."
while grep -q 'mdState="STARTED"' /var/local/emhttp/var.ini 2>/dev/null; do
    sleep 2
    echo -n "."
done
echo ""
echo "Array stopped."
ARRAY_EOF
    chmod +x /usr/local/bin/array-stop
    
    cat > /usr/local/bin/array-start << 'ARRAY_EOF'
#!/bin/bash
echo "Starting array..."
/usr/local/sbin/emcmd cmdStart=Start
echo "Waiting for array to start..."
while ! grep -q 'mdState="STARTED"' /var/local/emhttp/var.ini 2>/dev/null; do
    sleep 2
    echo -n "."
done
echo ""
echo "Array started."
ARRAY_EOF
    chmod +x /usr/local/bin/array-start
    
    cat > /usr/local/bin/array-restart << 'ARRAY_EOF'
#!/bin/bash
array-stop
sleep 3
array-start
ARRAY_EOF
    chmod +x /usr/local/bin/array-restart
    print_success "Installed array control scripts (array-stop, array-start, array-restart)"
    
    # Set up log cleanup cron immediately
    echo "0 3 * * * find /var/log -name '*.1' -o -name '*.2' -o -name '*.gz' | xargs rm -f 2>/dev/null" | crontab -
    print_success "Added daily log cleanup cron job (3am)"
else
    print_warning "unraid/go not found, skipping"
fi

print_header "Step 8: Build and Start Docker Services"

echo "Building Docker images..."
cd "$SCRIPT_DIR"

# Build all services
docker compose build

if [ $? -eq 0 ]; then
    print_success "Docker images built successfully"
else
    print_error "Docker build failed"
    exit 1
fi

if confirm "Start all services now?" "y"; then
    docker compose up -d
    
    if [ $? -eq 0 ]; then
        print_success "All services started"
    else
        print_error "Failed to start services"
    fi
else
    print_warning "Services not started"
    echo "You can start them later with: docker compose up -d"
fi

print_header "Installation Complete!"

echo "Configuration Summary:"
echo "  Server IP:      $SERVER_IP"
echo "  Immich Server:  $IMMICH_SERVER"
echo "  Google Drive:   $GDRIVE_PATH"
echo "  Imports:        $IMPORTS_PATH"
echo "  Metadata:       $IMPORTS_PATH/metadata"
echo "  State:          $STATE_DIR"
echo ""
echo "Services:"
docker compose ps --format "table {{.Name}}\t{{.Status}}"
echo ""
echo "Web Interfaces:"
echo "  Metadata Viewer: http://$SERVER_IP:5050"
echo "  Login Helper VNC: http://$SERVER_IP:6901"
echo ""
echo "Useful Commands:"
echo "  View logs:           docker compose logs -f [service]"
echo "  Restart service:     docker compose restart [service]"
echo "  Rebuild and restart: docker compose build [service] && docker compose up -d [service]"
echo ""
echo "Scheduled Tasks (via Chadburn):"
echo "  01:00 - version-watcher: Check for kasmweb/chrome updates"
echo "  01:05 - login-helper:    Check Google login status"
echo "  01:10 - automated-takeout: Create new Takeout exports"
echo "  04:00 - takeout-backup:  Sync Takeout from Google Drive"
echo "  05:00 - gdrive-backup:   Sync full Google Drive"
echo "  */15  - immich-import:   Import photos to Immich"
echo ""

if [ ! -f "$API_KEY_FILE" ] || [ ! -s "$API_KEY_FILE" ]; then
    print_warning "Reminder: Immich API key not configured"
    echo "Run the following to set it up:"
    echo "  1. Create API key at: $IMMICH_SERVER/user-settings?isOpen=api-keys"
    echo "  2. Save to: $API_KEY_FILE"
fi

echo ""
print_success "Installation complete!"
