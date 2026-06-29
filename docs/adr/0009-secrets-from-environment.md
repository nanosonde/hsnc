# ADR 0009 — Secrets only from the environment

**Status:** Accepted

## Context

Device SSH passwords and SNMPv3/Prometheus credentials are sensitive. Storing
them in `devices.yaml` would leak secrets into version control, backups and
diffs, and conflate "how to reach a device" with credentials.

## Decision

`devices.yaml` holds only non-secret connection details. All secrets resolve from
the environment: platform fallbacks (`HSNC_OPENWRT_SSH_PASSWORD`,
`HSNC_JETSTREAM_SSH_PASSWORD`), per-device overrides (`HSNC_DEVICE_<ID>_*`), and
`HSNC_SNMP_*` / `HSNC_PROMETHEUS_*`. `<ID>` is the device id upper-cased with
non-alphanumerics replaced by `_`.

## Consequences

- Inventory is safe to commit and back up; secrets stay out of YAML.
- Deployment supplies a git-ignored `.env`.
- Per-device overrides follow one consistent naming rule across all transports.
