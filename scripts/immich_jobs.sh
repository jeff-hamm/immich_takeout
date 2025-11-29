#!/bin/bash
# Wrapper script for immich_jobs.py
# Usage: immich_jobs.sh [resume|pause|status] [options]

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

python3 "$SCRIPT_DIR/immich_jobs.py" "$@"
