#!/bin/bash
# immich-go wrapper script for Unraid
# This allows the SD card import script to call immich-go via Docker

# Determine script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load environment variables from .env file (configurable path)
# Try local env file first, then fall back to configured path
if [ -f "$SCRIPT_DIR/immich-go-upload.env" ]; then
    source <(grep -v '^#' "$SCRIPT_DIR/immich-go-upload.env" | sed 's/^/export /')
else
    ENV_FILE="${TAKEOUT_SCRIPT_ENV:-/mnt/user/appdata/takeout-script/.env}"
    if [ -f "$ENV_FILE" ]; then
        source <(grep -v '^#' "$ENV_FILE" | sed 's/^/export /')
    fi
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
API_KEY_FILE="${IMMICH_API_KEY_FILE:-/mnt/user/appdata/takeout-script/cache/.immich_api_key}"

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

# Run immich-go binary directly
immich-go upload from-folder \
    --server "$IMMICH_SERVER" \
    --api-key "$IMMICH_API_KEY" \
    --tag "SD-IMPORT/$IMPORT_DATE" \
    --session-tag \
    --manage-raw-jpeg=StackCoverRaw \
    --log-file=/var/log/immich-go/upload-$IMPORT_DATE.log \
    --on-errors=continue \
    --manage-burst=Stack \
    "$UPLOAD_PATH"
