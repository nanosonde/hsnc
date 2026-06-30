# JetStream switch setup

TP-Link JetStream switches are configured over the SSH CLI (configuration plane)
and polled for live runtime data over **SNMPv3** (monitoring plane). The
monitoring plane never uses SSH.

## 1. SSH CLI — configuration plane (required)

Configuration uses the interactive SSH CLI. (JetStream switches reject one-shot
`exec` channels, so HSNC drives a single interactive shell session.)

1. Enable SSH from the switch CLI:

   ```text
   enable
   configure
   ip ssh server
   line vty
     login local
     exit
   exit
   ```

2. Create/confirm an admin user and provide its password to HSNC via the
   environment — never in `devices.yaml`:

   ```sh
   # global default for all JetStream switches
   HSNC_JETSTREAM_SSH_PASSWORD=...
   # or per device (id upper-cased, non-alphanumerics -> _)
   HSNC_DEVICE_SWITCH_1_PASSWORD=...
   ```

3. Inventory entry — the SSH connection profile:

   ```yaml
   - id: switch-1
     name: TL-SG2210P
     kind: switch
     ip: 192.168.50.2
     connection:
       username: admin
       port: 22
     monitoring:
       enabled: true
   ```

### Apply safety (rollback)

JetStream switches have no transactional config staging — each `configure`
command changes the running-config immediately, and `copy running-config
startup-config` is the only durable save. To avoid leaving a switch
half-configured, HSNC's apply:

1. snapshots the current running-config,
2. pushes the new config **without** saving,
3. saves to startup-config **only** if every command applied without a `%`
   error, and
4. on any failure (a rejected command or a dropped connection) re-pushes the
   snapshot to restore the running-config and leaves startup-config untouched.

The restore re-asserts the previous hostname/VLANs/ports but issues no deletes,
so a VLAN created by a partial push may linger until the next apply; because
startup-config is never written on failure, a switch reload always recovers the
last-known-good configuration.

## 2. SNMPv3 — monitoring plane (required)

Live runtime data is read over SNMPv3, never the SSH CLI. Configure an SNMPv3
user (USM, `authPriv` recommended) on the switch.

### Configure SNMPv3 on the switch

```text
enable
configure
snmp-server
snmp-server engineID local
snmp-server group hsncgrp v3 priv read defaultview
snmp-server user hsncmon hsncgrp v3 \
  auth sha <AUTH_PASSWORD> priv aes <PRIV_PASSWORD>
exit
```

> Exact command syntax varies by JetStream model/firmware; the goal is an
> SNMPv3 USM user with SHA auth and AES privacy that can read the standard
> MIB-II and BRIDGE-MIB trees.

### Point HSNC at the switch

By default HSNC uses the device IP on UDP/161, so no `monitoring` block is
required. Override the host/port only if SNMP answers elsewhere:

```yaml
- id: switch-1
  name: TL-SG2210P
  kind: switch
  ip: 192.168.50.2
  connection:
    username: admin
    port: 22
  monitoring:
    enabled: true
    endpoint: 192.168.50.2   # optional; defaults to the device ip
    port: 161                # optional; defaults to 161
```

`endpoint` may be `host` or `host:port`. If omitted, HSNC uses the device IP.
Set `enabled: false` to disable polling for a device (it then reports
`unknown`).

### Provide SNMPv3 credentials via the environment

Secrets never live in `devices.yaml`. Global defaults plus per-device overrides
(id upper-cased, non-alphanumerics -> `_`):

```sh
HSNC_SNMP_USER=hsncmon
HSNC_SNMP_AUTH_KEY=...        # auth password
HSNC_SNMP_PRIV_KEY=...        # privacy password
HSNC_SNMP_AUTH_PROTO=SHA      # SHA | MD5   (default SHA)
HSNC_SNMP_PRIV_PROTO=AES      # AES | DES   (default AES)
HSNC_SNMP_LEVEL=authPriv      # authPriv | authNoPriv | noAuthNoPriv
HSNC_SNMP_PORT=161

# per-device overrides:
HSNC_DEVICE_SWITCH_1_SNMP_USER=...
HSNC_DEVICE_SWITCH_1_SNMP_AUTH_KEY=...
HSNC_DEVICE_SWITCH_1_SNMP_PRIV_KEY=...
HSNC_DEVICE_SWITCH_1_SNMP_PORT=161
```

### Install the SNMP extra

The SNMP backend uses `pysnmp`, shipped as an optional extra:

```sh
pip install 'hsnc[snmp]'
```

### What HSNC reads

| Data | OID / MIB |
| --- | --- |
| Reachability | a successful SNMP GET -> `connected` |
| Name | `sysName.0` (`1.3.6.1.2.1.1.5.0`) |
| Model | `sysDescr.0` (`1.3.6.1.2.1.1.1.0`) |
| Uptime | `sysUpTime.0` (`1.3.6.1.2.1.1.3.0`, TimeTicks/100) |
| Clients | BRIDGE-MIB `dot1dTpFdbPort` (`1.3.6.1.2.1.17.4.3.1.2`); the MAC is taken from the OID suffix, the value is the bridge port |

## 3. Verify

From the HSNC host with `pysnmp` installed:

```sh
python3 - <<'PY'
import asyncio
from pysnmp.hlapi.v3arch.asyncio import (
    SnmpEngine, UsmUserData, UdpTransportTarget, ContextData,
    ObjectType, ObjectIdentity, get_cmd,
    usmHMACSHAAuthProtocol, usmAesCfb128Protocol,
)

async def main():
    transport = await UdpTransportTarget.create(('192.168.50.2', 161))
    err_indication, err_status, _idx, var_binds = await get_cmd(
        SnmpEngine(),
        UsmUserData('hsncmon', authKey='<AUTH>', privKey='<PRIV>',
                    authProtocol=usmHMACSHAAuthProtocol,
                    privProtocol=usmAesCfb128Protocol),
        transport,
        ContextData(),
        ObjectType(ObjectIdentity('1.3.6.1.2.1.1.5.0')))
    print(err_indication or err_status or var_binds)

asyncio.run(main())
PY
```

A returned `sysName` confirms the monitoring connection. HSNC's poll loop will
then read live data over SNMPv3 for this device.
