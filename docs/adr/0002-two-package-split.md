# ADR 0002 — Two standalone packages (backend + frontend)

**Status:** Accepted

## Context

The first version mixed web rendering and device I/O in one process. As the REST
surface matured it became clear the UI and the device-owning backend have
different lifecycles, dependencies and security boundaries. Keeping them tangled
risked the UI accidentally opening device connections in a request.

## Decision

Split the repo into two packages that **share no source code**:

- `hsnc/` (dist `hsnc`) — REST backend, owns device I/O and persistence.
- `hsncweb/` (dist `hsnc-web`) — frontend, pure presentation, calls the backend
  over HTTP.

Each has its own `pyproject.toml`, tests and README. They communicate only
through the JSON `/api`.

## Consequences

- Clear boundary: the frontend cannot touch devices or the DB.
- Either package can be developed, tested and deployed independently.
- A network hop and a wire contract (ADR 0005) must be maintained between them.
- Two installs in dev, two processes in the container (ADR 0012).
