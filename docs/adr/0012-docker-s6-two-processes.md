# ADR 0012 — Docker + s6-overlay, two supervised processes

**Status:** Accepted

## Context

The two-package split (ADR 0002) and backend-owned I/O (ADR 0005) mean deployment
must run two processes — the web UI and the always-on backend — share one data
volume, and seed config on first run. They need supervised lifecycle in a single
distributable image.

## Decision

Ship one Docker image running both processes under **s6-overlay**: `web`
(`gunicorn hsncweb.wsgi:app`) and `api` (`gunicorn hsnc.backend.wsgi:app`), with a
one-shot seed step that creates `devices.yaml` from the template if missing. Both
share `/data`. `docker-compose.yml` targets real hardware and requires the
inventory; mock mode needs no devices.

## Consequences

- Single image, supervised restarts, shared volume.
- Frontend reaches the backend over localhost inside the container.
- Two processes to monitor; s6 service definitions to maintain.
