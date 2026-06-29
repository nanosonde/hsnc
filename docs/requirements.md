# Requirements

Functional and non-functional requirements for hsnc, derived from the project's
history. Each requirement traces to one or more ADRs.

## Functional requirements

### Inventory & sites
- **FR-1** Manage a single site with a list of devices, kinds: gateway, switch,
  access point. (ADR 0002)
- **FR-2** Store device **connection profiles only** in `devices.yaml`; device
  configuration lives in `desired/current_config.json`. (ADR 0004, 0009)
- **FR-3** Add, quick-edit, re-read and delete devices from the UI.

### Configuration
- **FR-4** Edit VLANs (with CIDR-validated subnets), switch ports and SSIDs.
- **FR-5** Stage edits as pending changes; never push automatically. (ADR 0007)
- **FR-6** Review changes as a Current→New diff grouped by section, with the
  concrete OpenWrt UCI / JetStream CLI commands. (ADR 0007)
- **FR-7** Apply or revert per device, and apply-all / revert-all. (ADR 0007)
- **FR-8** Record every apply/baseline/revert with field-level detail in
  append-only history. (ADR 0004, 0007)

### Monitoring
- **FR-9** Poll devices in the background for status and connected clients.
  (ADR 0006)
- **FR-10** Select per device where live data comes from: primary (SSH),
  secondary (Prometheus/SNMPv3) or none; selection is strict. (ADR 0010)
- **FR-11** Dashboard, topology and live searchable/paginated client list.
- **FR-12** Show device status connected / disconnected / unknown; degrade
  gracefully when a device is unreachable. (ADR 0006)

### Operations
- **FR-13** Authn with admin and viewer roles. (ADR 0008)
- **FR-14** Read-only mode on by default; only admins toggle it. (ADR 0008)
- **FR-15** Export/import full state as one ZIP, UI and CLI. (ADR 0004)
- **FR-16** Two CLIs: `hsnc-ctl` (api/poll/backup), `hsnc-web` (serve).

## Non-functional requirements

- **NFR-1 Architecture:** Clean Architecture; inward dependencies; concretes
  wired only in `container.py`. (ADR 0001)
- **NFR-2 Decoupling:** backend and frontend share no source; HTTP only.
  (ADR 0002, 0005)
- **NFR-3 Responsiveness:** device I/O off the request path; offline devices
  never block the UI. (ADR 0005)
- **NFR-4 Simplicity:** no Node build; server-rendered + HTMX. (ADR 0003)
- **NFR-5 Security:** secrets only from env; AGPL; transcript/debug logs gated
  and warned. (ADR 0009, 0014)
- **NFR-6 Extensibility:** new platforms via per-platform packages behind ports.
  (ADR 0011)
- **NFR-7 Testability:** unit tests with fakes (no network/optional deps);
  integration vs fake SSH; demo via mocks. (ADR 0013)
- **NFR-8 Deployability:** single Docker image, two s6 processes, shared volume,
  config seeding. (ADR 0012)
- **NFR-9 Data retention:** prune runtime telemetry by `HSNC_RETENTION_DAYS`.
  (ADR 0004)

See the [ADRs](adr/README.md) for the rationale behind each requirement.
