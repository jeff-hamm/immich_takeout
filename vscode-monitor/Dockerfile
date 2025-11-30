# VS Code Monitor
# AI-powered container that monitors automated-takeout output and auto-fixes Playwright scripts
# Uses GitHub Copilot CLI (the new agentic CLI) for AI assistance

FROM node:22-slim

# Install util-linux for nsenter (needed for host namespace notifications)
# Install libvirt-clients for virsh (needed for VM healthchecks)
# Install smartmontools for smartctl (needed for disk health checks)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y \
    curl \
    jq \
    git \
    python3 \
    docker.io \
    util-linux \
    libvirt-clients \
    smartmontools \
    && rm -rf /var/lib/apt/lists/*

# Install GitHub CLI (gh) for creating pull requests
RUN curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && chmod go+r /usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] https://cli.github.com/packages stable main" | tee /etc/apt/sources.list.d/github-cli.list > /dev/null \
    && apt-get update \
    && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

# Install GitHub Copilot CLI globally
# This is the NEW agentic Copilot CLI (not the deprecated gh extension)
ARG COPILOT_VERSION=latest
RUN --mount=type=cache,target=/root/.npm \
    npm install -g @github/copilot@${COPILOT_VERSION}

# Configure git safe directories for mounted volumes
# These directories are mounted from the host and may have different ownership
RUN git config --global --add safe.directory /app && \
    git config --global --add safe.directory /state && \
    git config --global --add safe.directory '*'

# Configure git to use GH_TOKEN for authentication via credential helper
# This allows git push/pull to work with the GH_TOKEN environment variable
RUN git config --global credential.helper '!f() { echo "username=x-access-token"; echo "password=$GH_TOKEN"; }; f'

# Create directories
WORKDIR /app
RUN mkdir -p /app/logs /state/analysis

# Copy monitoring scripts
COPY monitor_takeout.py /app/
COPY copilot_prompt.md /app/
COPY send_alert.sh /usr/local/bin/send_alert
COPY alert_helper.py /app/
COPY host_cmd.sh /usr/local/bin/host_cmd
RUN chmod +x /usr/local/bin/send_alert /usr/local/bin/host_cmd

# Default to running the monitor script
CMD ["python3", "/app/vscode-monitor/monitor_takeout.py"]
