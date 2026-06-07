#!/bin/sh
# Oneshot run by s6-overlay (as root) before the long-running services start.
# Seeds the config volume on first run and fixes ownership of the data volume.
set -e

mkdir -p "${HSNC_CONFIG_DIR}" "${HSNC_DATA_DIR}"

MOCK="${HSNC_USE_MOCK_DEVICES:-1}"

# Copy baked-in config into the volume only if not already present (idempotent).
# devices.yaml is handled separately below (its seeding depends on the mode), and
# desired_config.json.example is the demo CONFIG payload that belongs in the data
# dir rather than the config dir, so both are skipped in this generic loop.
if [ -d /app/seed-config ]; then
  for f in /app/seed-config/*; do
    name="$(basename "$f")"
    case "$name" in
      desired_config.json.example) continue ;;
      devices.yaml.example) continue ;;
    esac
    # Templates (e.g. site.yaml, users.yaml) seed the real file name.
    target="${name%.example}"
    if [ ! -e "${HSNC_CONFIG_DIR}/${target}" ]; then
      cp "$f" "${HSNC_CONFIG_DIR}/${target}"
    fi
  done
fi

# Device inventory (devices.yaml) and demo payload depend on the mode.
case "${MOCK}" in
  0 | false | False)
    # Real-device deployment: the operator MUST supply their own inventory. We
    # never seed the bundled example here -- instead fail fast with guidance so a
    # misconfigured deployment does not silently start with no/sample devices.
    if [ ! -f "${HSNC_CONFIG_DIR}/devices.yaml" ]; then
      echo "FATAL: ${HSNC_CONFIG_DIR}/devices.yaml is missing." >&2
      echo "Real-device mode (HSNC_USE_MOCK_DEVICES=0) requires a device" >&2
      echo "inventory. Create one from config/devices.yaml.example, then mount" >&2
      echo "it at ${HSNC_CONFIG_DIR}/devices.yaml (see docker-compose.yml)." >&2
      exit 1
    fi
    ;;
  *)
    # Mock/demo mode: seed the sample inventory and the demo configuration
    # payload so the UI shows sample devices, VLANs, ports and SSIDs out of the
    # box without any hardware.
    if [ ! -e "${HSNC_CONFIG_DIR}/devices.yaml" ] \
       && [ -f /app/seed-config/devices.yaml.example ]; then
      cp /app/seed-config/devices.yaml.example "${HSNC_CONFIG_DIR}/devices.yaml"
    fi
    if [ -f /app/seed-config/desired_config.json.example ] \
       && [ ! -e "${HSNC_DATA_DIR}/desired_config.json" ]; then
      cp /app/seed-config/desired_config.json.example \
        "${HSNC_DATA_DIR}/desired_config.json"
    fi
    ;;
esac

# A freshly mounted named volume is root-owned; hand it to the runtime user so
# both the web and api services (which drop privileges) can read and write it.
# stderr is silenced because a read-only bind-mounted devices.yaml cannot be
# chowned and that warning is expected, not an error.
chown -R appuser:appuser "${HSNC_DATA_DIR}" 2>/dev/null || true
