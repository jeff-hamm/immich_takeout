FROM python:3.12-slim

# Install rclone from Debian repos (simpler than install script)
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y rclone && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY server_backup.py /app/server_backup.py

# Rclone config directory (will be mounted)
RUN mkdir -p /config/rclone
ENV RCLONE_CONFIG=/config/rclone/rclone.conf
ENV PYTHONUNBUFFERED=1

CMD ["python", "/app/server_backup.py"]
