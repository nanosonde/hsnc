# syntax=docker/dockerfile:1

# ---------- build stage ----------
FROM python:3.12-slim AS build

WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

COPY pyproject.toml README.md ./
COPY src ./src

# Build a wheel so the runtime image stays lean.
RUN python -m pip install --upgrade pip build \
    && python -m build --wheel --outdir /dist


# ---------- runtime stage ----------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    SDNMAN_CONFIG_DIR=/data/config \
    SDNMAN_DATA_DIR=/data \
    SDNMAN_USE_MOCK_DEVICES=1 \
    SDNMAN_POLL_INTERVAL=30 \
    SDNMAN_RETENTION_DAYS=30 \
    SDNMAN_BASELINE_ON_START=1 \
    SDNMAN_BROKER_SOCKET=/data/broker.sock

# s6-overlay supervises the long-running processes (web + broker) in a single
# container. Pinned; x86_64 only (adjust the arch tarball for other platforms).
ARG S6_OVERLAY_VERSION=3.2.0.2
ADD https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-noarch.tar.xz /tmp/s6-overlay-noarch.tar.xz
ADD https://github.com/just-containers/s6-overlay/releases/download/v${S6_OVERLAY_VERSION}/s6-overlay-x86_64.tar.xz /tmp/s6-overlay-x86_64.tar.xz
RUN apt-get update \
    && apt-get install -y --no-install-recommends xz-utils \
    && tar -C / -Jxpf /tmp/s6-overlay-noarch.tar.xz \
    && tar -C / -Jxpf /tmp/s6-overlay-x86_64.tar.xz \
    && rm -f /tmp/s6-overlay-*.tar.xz \
    && apt-get purge -y xz-utils \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Non-root user the services drop to (s6 init itself must start as root).
RUN useradd --create-home --uid 10001 appuser

WORKDIR /app

COPY --from=build /dist/*.whl /tmp/
RUN python -m pip install --no-cache-dir /tmp/*.whl gunicorn && rm -f /tmp/*.whl

# Seed configuration baked into the image; copied into the volume on first run.
COPY config /app/seed-config
# s6-overlay service definitions (seed-config oneshot -> web + broker longruns,
# baseline oneshot after the broker is up).
COPY docker/s6-overlay/s6-rc.d /etc/s6-overlay/s6-rc.d
COPY docker/s6-overlay/scripts/seed-config.sh /usr/local/bin/seed-config.sh
RUN chmod +x /usr/local/bin/seed-config.sh \
    /etc/s6-overlay/s6-rc.d/web/run \
    /etc/s6-overlay/s6-rc.d/broker/run \
    && mkdir -p /data && chown -R appuser:appuser /data /app

VOLUME ["/data"]
EXPOSE 8080

# /init brings up the s6 supervision tree; both services share /data.
ENTRYPOINT ["/init"]
