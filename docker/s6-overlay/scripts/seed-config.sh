#!/bin/sh
# Oneshot run by s6-overlay (as root) before the long-running services start.
# Seeds the config volume on first run and fixes ownership of the data volume.
set -e

mkdir -p "${SDNMAN_CONFIG_DIR}" "${SDNMAN_DATA_DIR}"

# Copy baked-in config into the volume only if not already present (idempotent).
if [ -d /app/seed-config ]; then
  for f in /app/seed-config/*; do
    name="$(basename "$f")"
    if [ ! -e "${SDNMAN_CONFIG_DIR}/${name}" ]; then
      cp "$f" "${SDNMAN_CONFIG_DIR}/${name}"
    fi
  done
fi

# A freshly mounted named volume is root-owned; hand it to the runtime user so
# both the web and poller services (which drop privileges) can read and write it.
chown -R appuser:appuser "${SDNMAN_DATA_DIR}" || true
