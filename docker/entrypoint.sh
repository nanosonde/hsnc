#!/bin/sh
set -e

# Seed the config volume on first run (idempotent: never overwrites existing files).
mkdir -p "${OMUI_CONFIG_DIR}"
if [ -d /app/seed-config ]; then
  for f in /app/seed-config/*; do
    name="$(basename "$f")"
    if [ ! -e "${OMUI_CONFIG_DIR}/${name}" ]; then
      cp "$f" "${OMUI_CONFIG_DIR}/${name}"
    fi
  done
fi

# The SQLite schema is migrated automatically on store construction (app start).
exec "$@"
