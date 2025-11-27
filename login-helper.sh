#!/bin/bash
# Helper script to start Chrome VNC for Google login

SERVER_IP="${SERVER_IP:-192.168.1.216}"
VNC_PORT="${VNC_PORT:-6901}"
COMPOSE_DIR="/root/stacks/gphotos-downloader"

echo "[INFO] Starting Chrome VNC service for Google login..."

cd "$COMPOSE_DIR" || exit 1

# Start the Chrome service with relogin profile
docker-compose --profile relogin up -d chrome

if [ $? -eq 0 ]; then
    echo ""
    echo "================================================================"
    echo "Chrome VNC is now running!"
    echo "================================================================"
    echo ""
    echo "Open in your browser:"
    echo "  http://${SERVER_IP}:${VNC_PORT}/"
    echo ""
    echo "Username: kasm_user"
    echo "Password: (check your .env or default VNC_PW)"
    echo ""
    echo "Once you've logged in to Google Photos:"
    echo "  1. Close the browser tab"
    echo "  2. Run: $0 stop"
    echo "  3. Run your automation script"
    echo ""
    echo "================================================================"
else
    echo "[ERROR] Failed to start Chrome service"
    exit 1
fi
