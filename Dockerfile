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
    OMADA_CONFIG_DIR=/data/config \
    OMADA_DATA_DIR=/data \
    OMADA_USE_MOCK_DEVICES=1 \
    OMADA_POLL_INTERVAL=30

# Non-root user
RUN useradd --create-home --uid 10001 appuser

WORKDIR /app

COPY --from=build /dist/*.whl /tmp/
RUN python -m pip install --no-cache-dir /tmp/*.whl gunicorn && rm -f /tmp/*.whl

# Seed configuration baked into the image; copied into the volume on first run.
COPY config /app/seed-config
COPY docker/entrypoint.sh /usr/local/bin/entrypoint.sh
RUN chmod +x /usr/local/bin/entrypoint.sh \
    && mkdir -p /data && chown -R appuser:appuser /data /app

USER appuser
VOLUME ["/data"]
EXPOSE 8080

ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", \
     "--timeout", "60", "omada_clone.presentation.wsgi:app"]
