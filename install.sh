#!/bin/bash
# Takeout Script Installation Script
# Builds and starts the Docker services for Google Photos backup
# For full system setup (rclone, API keys, etc), run: system-setup

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
STATE_DIR="$SCRIPT_DIR/state"

# Application name
APP_NAME="takeout-script"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_header() {
    echo ""
    echo -e "${BLUE}=========================================="
    echo "$1"
    echo -e "==========================================${NC}"
    echo ""
}

print_success() { echo -e "${GREEN}✓ $1${NC}"; }
print_warning() { echo -e "${YELLOW}⚠ $1${NC}"; }
print_error() { echo -e "${RED}✗ $1${NC}"; }

confirm() {
    local prompt="$1"
    local default="${2:-y}"
    local yn_hint="Y/n"
    [ "$default" = "n" ] && yn_hint="y/N"
    
    read -p "$prompt [$yn_hint]: " response
    response="${response:-$default}"
    [[ "$response" =~ ^[yY] ]]
}

print_header "Takeout Script Installation"

echo "This script will build and start the Docker services."
echo ""
echo "For full system setup (rclone, Chadburn, API keys, etc), run:"
echo "  system-setup"
echo ""

# Check if running as root
if [ "$EUID" -ne 0 ]; then 
    print_error "This script must be run as root"
    exit 1
fi

# Ensure state directory exists
mkdir -p "$STATE_DIR"

# Check for .env file
if [ ! -f "$SCRIPT_DIR/.env" ]; then
    print_warning "No .env file found"
    echo "You may want to run 'system-setup' first to configure the environment."
    echo ""
    if ! confirm "Continue anyway?" "n"; then
        exit 0
    fi
fi

print_header "Build and Start Docker Services"

echo "Building Docker images..."
cd "$SCRIPT_DIR"

# Build all services
if docker compose build; then
    print_success "Docker images built successfully"
else
    print_error "Docker build failed"
    exit 1
fi

if confirm "Start all services now?" "y"; then
    if docker compose up -d; then
        print_success "All services started"
    else
        print_error "Failed to start services"
        exit 1
    fi
else
    print_warning "Services not started"
    echo "You can start them later with: docker compose up -d"
fi

print_header "Installation Complete!"

echo "Services:"
docker compose ps --format "table {{.Name}}\t{{.Status}}"
echo ""
echo "Useful Commands:"
echo "  View logs:           docker compose logs -f [service]"
echo "  Restart service:     docker compose restart [service]"
echo "  Rebuild and restart: docker compose build [service] && docker compose up -d [service]"
echo ""
echo "For full system configuration, run: system-setup"
echo ""

print_success "Installation complete!"
