# ADR 0007 — Declarative config with staged review/apply/revert

**Status:** Accepted

## Context

Pushing edits straight to hardware is risky and opaque: mistakes hit live
networks instantly, with no preview and no easy undo. Operators need to see
exactly what will change before it ships.

## Decision

Treat the controller as source of truth. Edits are staged as **pending changes**
(`desired_config.json`) against a **baseline** (`current_config.json`). The
Review & Apply view shows a Current→New diff, the concrete commands (OpenWrt UCI
diff / JetStream CLI), and per-device **Apply** / **Revert** (plus apply-all).
Every apply is recorded field-by-field in append-only history; reverts restore
the baseline. Apply uses a dry-run plan and applies only changed devices.

## Consequences

- Changes are previewable, reversible and auditable.
- Re-read refreshes the baseline when a device changes out-of-band.
- Requires diff/plan/render machinery per platform.
