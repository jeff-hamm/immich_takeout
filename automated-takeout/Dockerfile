FROM python:3.12-slim

WORKDIR /app


COPY requirements.txt /app/
RUN --mount=type=cache,target=/root/.cache/pip \
    pip3 install -r requirements.txt && \
    playwright install --with-deps chromium
COPY automated_takeout.py /app/
COPY album_state.yml /app/

ENTRYPOINT ["python", "/app/automated_takeout.py"]
CMD []
