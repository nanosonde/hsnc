# Managing devices

A device is added to hsnc by listing it in `config/devices.yaml`. That file holds
**connection profiles only** — how to reach each device. The actual configuration
(VLANs, ports, SSIDs, model, firmware) is read from the hardware and stored
separately; it is never hand-written in YAML.

## Inventory entry

```yaml
devices:
  - id: gateway-1            # stable id (used in env-var overrides)
    name: ER605              # display name
    kind: gateway            # gateway | switch | access_point
    ip: 192.168.50.254       # management IP
    site_id: default
    connection:              # SSH access; password comes from the environment
      username: root
      port: 22
    monitoring:              # where live data is polled from (optional)
      source: primary        # primary | secondary | none
```

`devices.yaml` is environment-specific and git-ignored. Copy the shipped template
to start: `cp config/devices.yaml.example config/devices.yaml`.

## The two planes

hsnc reaches a device on two independent channels:

```mermaid
flowchart TB
    subgraph hsnc
      CFG[Config plane]
      MON[Monitoring plane]
    end
    CFG -->|SSH only: read/write VLANs, ports, SSIDs| DEV[Device]
    MON -->|primary: SSH scrape| DEV
    MON -->|secondary: Prometheus / SNMPv3| DEV
```

- **Configuration** is always SSH (OpenWrt UCI, JetStream CLI).
- **Monitoring** picks live status/clients via `monitoring.source`:
  - `primary` — scrape over SSH (no extra device setup),
  - `secondary` — a dedicated channel (Prometheus for OpenWrt, SNMPv3 for
    switches),
  - `none` — disable polling; the device shows `unknown`.

Selection is strict: a `secondary` device is never silently polled over SSH. Set
up the secondary channel per platform in [device setup](../devices/README.md).

## Device status

| Status | Meaning |
| --- | --- |
| `connected` | reachable, up |
| `disconnected` | reachable, reported down |
| `unknown` | unreachable or no monitoring source |

One unreachable device never blocks the UI or affects the others.

## Device actions in the UI

- **Re-read** a device to refresh the baseline from the hardware.
- **Quick-edit** name/IP and the connection profile.
- **Delete** a device from the inventory.
- **View SSH connection** to see the live transcript for diagnostics.

Secrets are never stored in the inventory — SSH passwords and SNMP/Prometheus
credentials all come from the environment.
