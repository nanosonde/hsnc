# syntax=docker/dockerfile:1

# ---------- build stage ----------
FROM python:3.12-slim AS build

WORKDIR /app
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1

COPY README.md ./
COPY hsnc ./hsnc
COPY hsncweb ./hsncweb

# Build a wheel per package so the runtime image stays lean and the two code bases
# stay independent.
RUN python -m pip install --upgrade pip build \
    && python -m build --wheel --outdir /dist ./hsnc \
    && python -m build --wheel --outdir /dist ./hsncweb


# ---------- runtime stage ----------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    HSNC_CONFIG_DIR=/data/config \
    HSNC_DATA_DIR=/data \
    HSNC_USE_MOCK_DEVICES=1 \
    HSNC_POLL_INTERVAL=30 \
    HSNC_RETENTION_DAYS=30 \
    HSNC_BASELINE_ON_START=1 \
    HSNC_API_BASE_URL=http://127.0.0.1:8081 \
    S6_BEHAVIOUR_IF_STAGE2_FAILS=2

# s6-overlay supervises the long-running processes (web frontend + REST backend)
# in a single container. Pinned; x86_64 only (adjust the arch tarball for other
# platforms).
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
# Install both wheels. The backend gets the [ssh] extra so real-device mode
# (paramiko) works out of the box; gunicorn is a dependency of both.
RUN python -m pip install --no-cache-dir "$(ls /tmp/hsnc-*.whl)[ssh]" $(ls /tmp/hsnc_web-*.whl) \
    && rm -f /tmp/*.whl

# Seed configuration baked into the image; copied into the volume on first run.
COPY config /app/seed-config
# s6-overlay service definitions (seed-config oneshot -> api + web longruns;
# the api backend reads the baseline and polls internally, no separate oneshot).
COPY docker/s6-overlay/s6-rc.d /etc/s6-overlay/s6-rc.d
COPY docker/s6-overlay/scripts/seed-config.sh /usr/local/bin/seed-config.sh
RUN chmod +x /usr/local/bin/seed-config.sh \
    /etc/s6-overlay/s6-rc.d/web/run \
    /etc/s6-overlay/s6-rc.d/api/run \
    && mkdir -p /data && chown -R appuser:appuser /data /app

VOLUME ["/data"]
EXPOSE 8080

# /init brings up the s6 supervision tree; both services share /data.
ENTRYPOINT ["/init"]
