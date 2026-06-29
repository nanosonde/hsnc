# ADR 0004 — YAML config · SQLite telemetry · JSONL history

**Status:** Accepted

## Context

The controller stores three very different kinds of data: declarative inventory
(hand-edited, diff-friendly), high-volume time-varying telemetry (queried per
page, pruned), and an audit trail of applies (append-only, must survive
restarts). No single store fits all three well.

## Decision

Use the right tool per concern:

- **YAML** for site/users/device inventory — human-readable, version-control
  friendly, easy to template.
- **SQLite** (WAL mode) for runtime telemetry — efficient queries, retention
  pruning, single-file.
- **append-only JSONL** for apply history — trivial to append, tail and back up.

The backend is the sole writer of all three. Device *configuration* (VLANs/ports/
SSIDs) is not in YAML; it lives in `desired_config.json` / `current_config.json`.

## Consequences

- Inventory diffs cleanly in git; telemetry scales without bloating YAML.
- One backup ZIP bundles all stores (ADR 0005/0007 workflows depend on it).
- Three storage formats to understand, but each is simple and isolated.
