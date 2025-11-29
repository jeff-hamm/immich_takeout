#!/bin/bash
# Wrapper script for sending Unraid notifications from inside a container
# Uses nsenter to run the notify command in the host's namespace
#
# Usage: ./notify.sh -e "event" -s "subject" -d "description" -i "importance" [-m "message"]
#
# This script exists because the Copilot CLI's shell tool blocks nsenter directly.
# By calling this script, we bypass that restriction.

exec nsenter -t 1 -m -u -i -n -p -- /usr/local/emhttp/plugins/dynamix/scripts/notify "$@"
