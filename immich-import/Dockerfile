FROM python:3.12-slim
# Install immich-go using direct download method
WORKDIR /tmp
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    --mount=type=cache,target=/tmp/downloads \
    apt-get update && \
    apt-get install -y wget ca-certificates && \
    wget -O immich-go.tar.gz https://github.com/simulot/immich-go/releases/latest/download/immich-go_Linux_x86_64.tar.gz && \
    tar -xzf immich-go.tar.gz && \
    mv immich-go /usr/local/bin/ && \
    chmod +x /usr/local/bin/immich-go && \
    rm immich-go.tar.gz && \
    apt-get remove -y wget && \
    apt-get autoremove -y && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

WORKDIR /app
ENV PYTHONUNBUFFERED=1

# Build args for default configuration
ARG IMMICH_SERVER
ARG IMMICH_API_KEY_FILE
ARG IMMICH_API_KEY

# Set as environment variables
ENV IMMICH_SERVER=${IMMICH_SERVER}
ENV IMMICH_API_KEY_FILE=${IMMICH_API_KEY_FILE}
ENV IMMICH_API_KEY=${IMMICH_API_KEY}

# Copy shared module (must be copied into build context)
COPY shared /app/shared
COPY immich-import/immich_import.py /app/immich_import.py

ENTRYPOINT ["python", "/app/immich_import.py"]
CMD []
