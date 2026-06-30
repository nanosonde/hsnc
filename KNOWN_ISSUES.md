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

### `device_ids` are filtered, not validated; removed devices are skipped silently

- **Current behavior:** `ApplyConfig.execute(device_ids=...)` uses `device_ids`
  purely as a membership filter. Unknown/typo/stale IDs are silently ignored
  (no error, no result row), and devices that were *removed* from config are
  never pushed, cleaned up, or reported in `ApplyResult` / apply history. See
  [`hsnc/src/hsnc/use_cases/apply_config.py`](hsnc/src/hsnc/use_cases/apply_config.py).
- **Risk:** Callers get no feedback when they request an ID that no longer
  exists, and decommissioned devices leave stale config on the hardware.
- **Why deferred:** `ApplyResult` / `DeviceApplyResult` and the apply-history
  entries are a caller-visible contract consumed by the REST backend, the web
  frontend, and golden/route tests. Adding validation (raising on unknown IDs)
  or representing removed devices changes which entries appear and when errors
  are raised — a product/semantics decision, not a pure internal fix.
- **Status:** Deferred pending a decision on the intended semantics.

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

