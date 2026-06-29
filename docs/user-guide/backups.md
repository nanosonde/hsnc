# Backups

A backup is a single ZIP containing the full controller state: YAML config, the
staged and baseline configuration, the runtime telemetry database and the apply
history. Import restores all of it.

## From the UI (admin only)

**Backup → Download** to export, **Backup → Import** to restore.

## From the CLI

```bash
hsnc-ctl backup export ./backup.zip
hsnc-ctl backup import ./backup.zip
```

## What's inside

| Item | Source |
| --- | --- |
| Site / users / devices | `config/*.yaml` |
| Staged edits | `desired_config.json` |
| Baseline | `current_config.json` |
| Runtime telemetry | `runtime.db` |
| Apply history | `history.jsonl` |

## Recommended practice

- Export before applying large changes or upgrading.
- Importing **replaces** current state — take a fresh export first if unsure.
- Backups contain hashed user passwords and device connection profiles, but never
  device SSH passwords or SNMP/Prometheus secrets — those live only in the
  environment. Store backups securely regardless.
