# ADR 0005 — Backend owns all device I/O over a REST API

**Status:** Accepted (supersedes the Device Broker)

## Context

Opening SSH connections inside web requests made pages slow and fragile: an
unreachable device could block the UI. An early **Device Broker** moved I/O out
of the request path over an IPC channel, but added a bespoke subsystem to
maintain. The two-package split (ADR 0002) needed a clean contract between web
and device-owning code.

## Decision

Make the **backend** the always-on owner of all device I/O. It opens each
device's configuration-plane SSH connection on demand and keeps it warm (one
supervisor thread per device, reconnecting independently) until it falls idle,
records polled telemetry, and exposes a JSON `/api`. The frontend holds no
connections and calls the backend over HTTP for every read and write. The
bespoke broker IPC was removed and replaced by this unified REST backend.

## Consequences

- The UI is fast — device I/O never sits in a request; an offline device can't
  block a page.
- A stable JSON wire contract (serialization + error envelope) is required.
- A single backend process is the source of truth and the only DB writer.
- Superseded: the broker subsystem no longer exists.
