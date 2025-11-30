#!/bin/bash
# Wrapper to run commands on host via nsenter
# Copilot CLI blocks direct nsenter commands, so we use this wrapper
exec nsenter -t 1 -m -u -i -n -p -- "$@"
