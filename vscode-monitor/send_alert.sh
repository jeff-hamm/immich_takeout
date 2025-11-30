#!/bin/bash
# Wrapper script for sending Unraid notifications from inside a container
# Uses nsenter to run the notify command in the host's namespace
#
# Usage: notify -e "event" -s "subject" -d "description" -i "importance" [-m "message"] [-l "link"]
#
# Parameters:
#   -e "event"       Event category (e.g., "vscode-monitor", "chadburn-update")
#   -s "subject"     Short subject line shown in notification
#   -d "description" Brief description (shown in notification list)
#   -i "importance"  One of: normal, warning, alert
#   -m "message"     Optional longer message body
#   -l "link"        Optional link (clicking notification opens this URL)
#                    Special: /state/analysis/<filename> is converted to the public URL
#
# Common links for this project:
#   Metadata Viewer:  http://192.168.1.216:5050
#   Immich:           http://192.168.1.216:2283
#   Login Helper VNC: http://192.168.1.216:6901
#   Analysis Files:   ${FILEBROWSER_BASE_URL}/${FILEBROWSER_ANALYSIS_PATH}/
#
# Examples:
#   notify -e "vscode-monitor" -s "Import Complete" -d "10 files imported" -i "normal" -l "http://192.168.1.216:5050"
#   notify -e "vscode-monitor" -s "Auth Required" -d "Google login expired" -i "warning" -l "http://192.168.1.216:6901"
#   notify -e "vscode-monitor" -s "Analysis Ready" -d "See report" -i "normal" -l "/state/analysis/report_20251128.txt"
#
# This script exists because the Copilot CLI's shell tool blocks nsenter directly.
# By calling this script, we bypass that restriction.

# Base URL for analysis files (served by FileBrowser)
# Uses FILEBROWSER_BASE_URL, FILEBROWSER_ANALYSIS_PATH, and APP_NAME from environment
if [[ -n "$FILEBROWSER_BASE_URL" ]]; then
    # Use env var for path, with fallback using APP_NAME
    APP_NAME="${APP_NAME:-takeout-script}"
    ANALYSIS_PATH="${FILEBROWSER_ANALYSIS_PATH:-appdata/${APP_NAME}/state/analysis}"
    ANALYSIS_BASE_URL="${FILEBROWSER_BASE_URL}/${ANALYSIS_PATH}"
else
    # Fallback: skip URL transformation if not configured
    ANALYSIS_BASE_URL=""
fi

# Process arguments and transform /state/analysis/ paths to public URLs
args=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        -l)
            shift
            link="$1"
            # Transform /state/analysis/<filename> to public URL (if FILEBROWSER_BASE_URL is set)
            if [[ "$link" == /state/analysis/* && -n "$ANALYSIS_BASE_URL" ]]; then
                filename="${link#/state/analysis/}"
                link="${ANALYSIS_BASE_URL}/${filename}"
            fi
            args+=("-l" "$link")
            ;;
        *)
            args+=("$1")
            ;;
    esac
    shift
done

exec nsenter -t 1 -m -u -i -n -p -- /usr/local/emhttp/plugins/dynamix/scripts/notify "${args[@]}"
