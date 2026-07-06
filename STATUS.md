# Project status

A snapshot of what currently works and what does not. For the rationale behind
each capability see the [ADRs](docs/adr/README.md) and
[requirements](docs/requirements.md). The **Not working / limitations** section
below lists accepted limitations and deferred hardening items: each entry
explains the current behavior, the risk, and why it has not yet been changed so
the trade-off is a deliberate decision rather than an oversight.

## Working

### Device drivers & planes
- OpenWrt SSH/UCI configuration driver, fully implemented and tested. (ADR 0006, FR-4, FR-6)
- JetStream SSH/CLI configuration driver, fully implemented and tested. (ADR 0006, FR-4, FR-6)
- Config plane over SSH only; monitoring plane never uses SSH. (ADR 0006, 0015, FR-10)
- Prometheus exporter reader for OpenWrt gateways/APs (monitoring plane). (ADR 0015, FR-10)
- SNMPv3 reader for JetStream switches (monitoring plane). (ADR 0015, FR-10)
- Per-device monitoring selected by a `MonitoringProviderFactory`; polling can be disabled per device. (ADR 0015, FR-10)
- Graceful degradation: an unreachable/misconfigured device reports `UNKNOWN` instead of masking the failure, and never blocks other devices or the UI. (ADR 0006, NFR-3, FR-12)

### Configuration & apply
- Edit VLANs (CIDR-validated subnets), switch ports and SSIDs. (FR-4)
- Edits staged as pending changes; nothing is pushed until you apply. (ADR 0007, FR-5)
- Review as a Current → New diff grouped by section, with the concrete UCI / CLI commands and a LuCI-style UCI field diff for OpenWrt. (ADR 0007, FR-6)
- Apply / revert per device, plus Apply All / Revert All. (ADR 0007, FR-7)
- Append-only apply/baseline/revert history with field-level detail. (ADR 0004, 0007, FR-8)
- Read-only mode on by default; only admins can toggle it. (ADR 0008, FR-14)

### Runtime & storage
- Background polling for status and connected clients. (ADR 0006, FR-9)
- Dashboard, topology and a live searchable/paginated client list. (FR-11)
- Backend owns all device I/O off the request path; demand-driven warm SSH connections with idle timeout. (ADR 0005, NFR-3)
- Polyglot storage: YAML config, SQLite runtime telemetry (WAL) with retention pruning, JSONL apply history. (ADR 0004, NFR-9)
- Startup baseline reads each device's live config into `current_config.json`. (ADR 0007, FR-8)

### Operations & packaging
- Two independent packages sharing no source; frontend reaches the backend over HTTP only. (ADR 0002, 0005, NFR-2)
- Server-rendered Jinja2 + HTMX frontend, no Node build. (ADR 0003, NFR-4)
- Authn with admin and viewer roles. (ADR 0008, FR-13)
- Full-state ZIP export/import from both the UI and CLI. (ADR 0004, FR-15)
- Two CLIs: `hsnc-ctl` (api/poll/backup) and `hsnc-web` (serve). (FR-16)
- Secrets resolved only from the environment, never from YAML. (ADR 0009, NFR-5)
- Single Docker image running two s6-supervised processes over a shared volume, with config seeding. (ADR 0012, NFR-8)

### Development & testing
- Unit tests with fakes (no network or optional dependencies). (ADR 0013, NFR-7)
- In-process mock providers for a hardware-free demo (`HSNC_USE_MOCK_DEVICES=1`). (ADR 0013, NFR-7)
- Throwaway fake device simulators in [`fakes/`](fakes/) answering both planes, exercised by `make integration`. (ADR 0013, NFR-7)

## Not working / limitations

### SSH host keys default to trust-on-first-use (`HSNC_SSH_ACCEPT_UNKNOWN_HOSTS=1`)
- **Current behavior:** An unknown host key is auto-accepted (`paramiko.AutoAddPolicy`); the default is accept, controlled by `HSNC_SSH_ACCEPT_UNKNOWN_HOSTS` (`1`/default = accept, `0` = reject). See [`hsnc/src/hsnc/devices/ssh_transport.py`](hsnc/src/hsnc/devices/ssh_transport.py).
- **Risk:** Trust-on-first-use does not verify a device's identity on first connect, leaving a man-in-the-middle window on an untrusted network. A more secure default would reject unknown keys and require them pre-seeded in `known_hosts`, with auto-accept as an explicit opt-in.
- **Why deferred:** Rejecting by default breaks the mock device containers and smoke test as written — the fakes are reached over freshly generated host keys that are not pre-seeded, so `make integration` / `fakes/smoke_test.sh` would fail on first connect.
- **Workaround:** Operators on untrusted networks can set `HSNC_SSH_ACCEPT_UNKNOWN_HOSTS=0` today for reject-by-default behavior.
- **Status:** Accepted for now; revisit when the fakes harness can pre-seed host keys. (ADR 0009, NFR-5)

### Read-only mode is enforced only in the web tier
- **Current behavior:** Read-only mode is enforced by the web `_enforce_read_only` before_request handler, by design — the REST backend is the device-I/O plane and has no read-only concept. A caller using a backend API token directly is not gated by read-only.
- **Status:** Accepted; tracked as potential future work. (ADR 0008, 0006)

### No concurrency lock around apply
- **Current behavior:** There is no lock around apply, so overlapping apply runs could race on the applied snapshot.
- **Status:** Accepted; tracked as potential future work. (ADR 0007)

### JetStream apply rollback is best-effort (additive), not a full inverse
- **Current behavior:** `JetStreamCliAdapter.push_config` snapshots the running-config, pushes the new config without saving, persists to startup-config only when every command applied without a `%` error, and on failure re-pushes the snapshot to restore the running-config while leaving startup-config as the last-known-good. See [`hsnc/src/hsnc/devices/jetstream/adapter.py`](hsnc/src/hsnc/devices/jetstream/adapter.py).
- **Remaining limitation:** The restore re-asserts previous hostname/VLANs/ports but issues no deletes (the renderer is additive), so a VLAN/port section created by a partial push can linger until the next apply. Because startup-config is never written on failure, a device reload always recovers the last-known-good config. A full inverse restore is out of scope for now. (ADR 0007)

### Only OpenWrt and JetStream platforms ship today
- **Current behavior:** Only the OpenWrt and JetStream drivers exist. New platforms slot in behind the existing ports without touching the config plane. (ADR 0011, NFR-6)
