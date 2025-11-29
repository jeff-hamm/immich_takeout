#!/bin/bash
# immich-go wrapper script for Unraid
# This allows the SD card import script to call immich-go via Docker

# Determine script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Try to find the main project .env file (parent directory of sd-import)
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
if [ -f "$PROJECT_DIR/.env" ]; then
    source <(grep -v '^#' "$PROJECT_DIR/.env" | grep -E '^[A-Z_]+=' | sed 's/^/export /')
fi

# Application name for path defaults
APP_NAME="${APP_NAME:-takeout-script}"

# Load environment variables from local .env file (overrides)
# Try local env file first, then fall back to configured path
if [ -f "$SCRIPT_DIR/immich-go-upload.env" ]; then
    source <(grep -v '^#' "$SCRIPT_DIR/immich-go-upload.env" | sed 's/^/export /')
fi

# Parse command line arguments
COMMAND=""
SERVER=""
KEY=""
UPLOAD_PATH=""

while [[ $# -gt 0 ]]; do
    case $1 in
        upload)
            COMMAND="upload"
            shift
            ;;
        -server=*)
            SERVER="${1#*=}"
            shift
            ;;
        -key=*)
            KEY="${1#*=}"
            shift
            ;;
        *)
            UPLOAD_PATH="$1"
            shift
            ;;
    esac
done

# Fall back to environment variables if not provided via arguments
IMMICH_SERVER="${SERVER:-${IMMICH_SERVER:-http://192.168.1.216:2283}}"
# APP_ROOT and APP_PATH come from .env, with fallbacks
APP_ROOT="${APP_ROOT:-/mnt/user/appdata}"
APP_PATH="${APP_PATH:-${APP_ROOT}/${APP_NAME}}"
API_KEY_FILE="${IMMICH_API_KEY_FILE:-${APP_PATH}/state/.immich_api_key}"

# Determine API key: command line > environment variable > file
if [ -n "$KEY" ]; then
    IMMICH_API_KEY="$KEY"
elif [ -n "$IMMICH_API_KEY" ]; then
    IMMICH_API_KEY="$IMMICH_API_KEY"
elif [ -f "$API_KEY_FILE" ]; then
    IMMICH_API_KEY=$(cat "$API_KEY_FILE" | tr -d '\n\r ')
else
    echo "ERROR: IMMICH_API_KEY not found in arguments, environment, or $API_KEY_FILE" >&2
    exit 1
fi

# Validate we have a path to upload
if [ -z "$UPLOAD_PATH" ]; then
    echo "ERROR: No upload path specified" >&2
    exit 1
fi

# Extract import date from path (format: YYYY-MM-DD_HHMMSS)
IMPORT_DATE=$(date +%Y%m%d)

# Run immich-import container in folder mode
# The container will handle the immich-go upload and metadata creation
docker run --rm \
    --name "sd-import-$IMPORT_DATE" \
    -e IMMICH_SERVER="$IMMICH_SERVER" \
    -e IMMICH_API_KEY="$IMMICH_API_KEY" \
    -e DELETE_AFTER_IMPORT=false \
    -v "$UPLOAD_PATH:/data/import:ro" \
    -v "${UPLOAD_PATH}/metadata:/data/metadata" \
    --network bridge \
    immich-import:latest \
    folder --source-type sd-card --label "$IMPORT_DATE"
