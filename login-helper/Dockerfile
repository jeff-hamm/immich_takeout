ARG BASE_IMAGE_VERSION=1.18.0
ARG BASE_IMAGE_TAG=${BASE_IMAGE_VERSION}-rolling-weekly
FROM kasmweb/chrome:${BASE_IMAGE_TAG}

USER root

# Install Python and dependencies
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    wget \
    && rm -rf /var/lib/apt/lists/*

# Install Playwright and PyYAML
RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install playwright && \
    playwright install --with-deps chromium

# Copy the check_login.py script
WORKDIR /app
COPY check_login.py /app/

# Create a wrapper script to check login status
COPY check_login.sh /app/check_login.sh
RUN chmod +x /app/check_login.sh

# Use the Kasm entrypoint with our custom startup script
ENTRYPOINT ["/app/check_login.sh"]
