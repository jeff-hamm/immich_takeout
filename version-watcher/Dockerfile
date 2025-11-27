FROM python:3.12-slim

WORKDIR /app

# Install docker-compose CLI
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y \
    curl \
    && curl -L "https://github.com/docker/compose/releases/latest/download/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose \
    && chmod +x /usr/local/bin/docker-compose \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install requests

# Copy version watcher script
COPY version_watcher.py /app/

# Make script executable
RUN chmod +x /app/version_watcher.py

CMD ["python", "/app/version_watcher.py"]
