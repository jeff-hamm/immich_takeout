FROM python:3.12-slim

# Install dependencies and latest rclone from official source
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && \
    apt-get install -y curl unzip ca-certificates && \
    curl https://rclone.org/install.sh | bash && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Rclone config directory (will be mounted)
RUN mkdir -p /config/rclone
ENV RCLONE_CONFIG=/config/rclone/rclone.conf
ENV PYTHONUNBUFFERED=1

# Copy shared module (must be copied into build context)
COPY shared /app/shared

COPY takeout-backup/server_backup.py /app/server_backup.py
CMD ["python", "/app/server_backup.py"]
