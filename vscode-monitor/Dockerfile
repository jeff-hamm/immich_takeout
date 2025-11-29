# VS Code Monitor
# AI-powered container that monitors automated-takeout output and auto-fixes Playwright scripts
# Uses GitHub Copilot CLI (the new agentic CLI) for AI assistance

FROM node:22-slim

# Install util-linux for nsenter (needed for host namespace notifications)
RUN apt-get update && apt-get install -y \
    curl \
    jq \
    git \
    python3 \
    docker.io \
    util-linux \
    && rm -rf /var/lib/apt/lists/*

# Install GitHub Copilot CLI globally
# This is the NEW agentic Copilot CLI (not the deprecated gh extension)
ARG COPILOT_VERSION=latest
RUN npm install -g @github/copilot@${COPILOT_VERSION}

# Configure git safe directories for mounted volumes
# These directories are mounted from the host and may have different ownership
RUN git config --global --add safe.directory /app/takeout-script && \
    git config --global --add safe.directory /app/chadburn && \
    git config --global --add safe.directory /app/automated-takeout && \
    git config --global --add safe.directory '*'

# Create directories
WORKDIR /app
RUN mkdir -p /app/logs /app/analysis

# Copy monitoring scripts
COPY monitor_takeout.py /app/
COPY copilot_prompt.md /app/
COPY notify.sh /usr/local/bin/notify
RUN chmod +x /usr/local/bin/notify

# Default to running the monitor script
CMD ["python3", "/app/vscode-monitor/monitor_takeout.py"]
