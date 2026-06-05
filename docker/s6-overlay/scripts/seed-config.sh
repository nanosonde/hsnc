#!/bin/sh
# Oneshot run by s6-overlay (as root) before the long-running services start.
# Seeds the config volume on first run and fixes ownership of the data volume.
set -e

mkdir -p "${SDNMAN_CONFIG_DIR}" "${SDNMAN_DATA_DIR}"

# Copy baked-in config into the volume only if not already present (idempotent).
# devices.yaml.example holds connection profiles only; desired_config.json.example
# is the demo CONFIG payload and belongs in the data dir, not the config dir, so
# it is handled separately below.
if [ -d /app/seed-config ]; then
  for f in /app/seed-config/*; do
    name="$(basename "$f")"
    case "$name" in
      desired_config.json.example) continue ;;
    esac
    # Templates (e.g. devices.yaml.example) seed the real file name.
    target="${name%.example}"
    if [ ! -e "${SDNMAN_CONFIG_DIR}/${target}" ]; then
      cp "$f" "${SDNMAN_CONFIG_DIR}/${target}"
    fi
  done
fi

# In mock mode, seed the demo configuration payload so the UI shows sample
# VLANs/ports/SSIDs out of the box. Real deployments leave this empty: the
# Device Broker reads the live baseline into current_config.json on start.
case "${SDNMAN_USE_MOCK_DEVICES:-1}" in
  0 | false | False) ;;
  *)
    if [ -f /app/seed-config/desired_config.json.example ] \
       && [ ! -e "${SDNMAN_DATA_DIR}/desired_config.json" ]; then
      cp /app/seed-config/desired_config.json.example \
        "${SDNMAN_DATA_DIR}/desired_config.json"
    fi
    ;;
esac

# A freshly mounted named volume is root-owned; hand it to the runtime user so
# both the web and broker services (which drop privileges) can read and write it.
chown -R appuser:appuser "${SDNMAN_DATA_DIR}" || true
