# Known Issues

A running list of accepted limitations and deferred hardening items. Each entry
explains the current behavior, the risk, and why it has not yet been changed so
the trade-off is a deliberate decision rather than an oversight.

## Security

### SSH host keys default to trust-on-first-use (`HSNC_SSH_ACCEPT_UNKNOWN_HOSTS=1`)

- **Current behavior:** When connecting to a real device over SSH, an unknown
  host key is auto-accepted (`paramiko.AutoAddPolicy`). The default is `accept`
  (`accept_unknown_hosts: bool = True`), controlled by the
  `HSNC_SSH_ACCEPT_UNKNOWN_HOSTS` environment variable (`1`/default = accept,
  `0` = reject). See
  [`hsnc/src/hsnc/devices/ssh_transport.py`](hsnc/src/hsnc/devices/ssh_transport.py).
- **Risk:** Trust-on-first-use does not verify a device's identity on the first
  connection, leaving a window for a man-in-the-middle on an untrusted network.
  A more secure default would be to **reject** unknown keys
  (`paramiko.RejectPolicy`) and require keys to be pre-seeded in
  `known_hosts`, with auto-accept as an explicit opt-in.
- **Why deferred:** Flipping the default to reject breaks the mock device
  containers and the smoke test as currently written — the fakes are reached
  over freshly generated host keys that are not pre-seeded, so `make integration`
  / `fakes/smoke_test.sh` would fail on first connect. Changing the default
  safely requires either seeding the mock host keys into a `known_hosts` file or
  having the fakes' harness opt back in explicitly.
- **Workaround / mitigation:** Operators on untrusted networks can set
  `HSNC_SSH_ACCEPT_UNKNOWN_HOSTS=0` today to get reject-by-default behavior.
- **Status:** Accepted for now; revisit when the fakes harness can pre-seed
  host keys so the secure default does not break local integration testing.

## Apply workflow

### `device_ids` validation and removed-device handling

- **Status:** Resolved. `ApplyConfig.execute(device_ids=...)` now reports an
  explicitly-requested id that matches no known device as a failed
  `DeviceApplyResult` (`"Unknown device id '<id>'."`) instead of silently doing
  nothing; an id that exists but has no pending changes stays a quiet no-op.
  Devices *removed* from the inventory were already deprovisioned (reported
  `ok=True "Removed from inventory."` and dropped from the applied snapshot). See
  [`hsnc/src/hsnc/use_cases/apply_config.py`](hsnc/src/hsnc/use_cases/apply_config.py).
- **Design note:** Validation is return-based (a failed result row), not an
  exception, so the `ApplyResult` JSON contract is preserved and a stale request
  never turns into a 5xx.
- **Remaining limitation:** Read-only mode is enforced only in the web tier
  (`_enforce_read_only` before_request), by design — the REST backend is the
  device-I/O plane and has no read-only concept (ADR-0008/0006). A caller using a
  backend API token directly is not gated by read-only. Likewise there is no
  concurrency lock around apply, so overlapping apply runs could race on the
  applied snapshot; both are tracked as potential future work.


## Device adapters

### JetStream apply rollback is best-effort (additive), not a full inverse

- **Status:** Largely resolved. `JetStreamCliAdapter.push_config` now snapshots
  the running-config, pushes the new config without saving, persists to
  startup-config only when every command applied without a `%` error, and on any
  failure re-pushes the snapshot to restore the running-config while leaving
  startup-config as the last-known-good. See
  [`hsnc/src/hsnc/devices/jetstream/adapter.py`](hsnc/src/hsnc/devices/jetstream/adapter.py).
- **Remaining limitation:** The restore re-asserts the previous
  hostname/VLANs/ports but issues no deletes (the renderer is additive), so a
  VLAN/port section created by a partial push can linger until the next apply.
  Because startup-config is never written on failure, a device reload always
  recovers the last-known-good config. A full inverse restore (emitting
  `no vlan`/`no interface` for sections a partial push added) is out of scope
  for now.

