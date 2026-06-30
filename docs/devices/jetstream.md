# JetStream switch setup

TP-Link JetStream switches are managed over the SSH CLI (configuration plane)
and can optionally be polled for live runtime data over **SNMPv3** (secondary
monitoring plane).

## 1. Primary connection — SSH CLI (required)

The configuration plane and the *primary* monitoring source both use the
interactive SSH CLI. (JetStream switches reject one-shot `exec` channels, so
HSNC drives a single interactive shell session.)

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

3. Inventory entry — primary polling needs no extra config:

   ```yaml
   - id: switch-1
     name: TL-SG2210P
     kind: switch
     ip: 192.168.50.2
     connection:
       username: admin
       port: 22
     monitoring:
       source: primary
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

## 2. Secondary connection — SNMPv3 (optional)

To poll runtime data over SNMPv3 instead of the SSH CLI, configure an SNMPv3
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

```yaml
- id: switch-1
  name: TL-SG2210P
  kind: switch
  ip: 192.168.50.2
  connection:
    username: admin
    port: 22
  monitoring:
    source: secondary
    secondary:
      type: snmp
      endpoint: 192.168.50.2   # optional; defaults to the device ip
      port: 161                # optional; defaults to 161
```

`endpoint` may be `host` or `host:port`. If omitted, HSNC uses the device IP.

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
from pysnmp.hlapi import *
it = getCmd(SnmpEngine(),
            UsmUserData('hsncmon', authKey='<AUTH>', privKey='<PRIV>',
                        authProtocol=usmHMACSHAAuthProtocol,
                        privProtocol=usmAesCfb128Protocol),
            UdpTransportTarget(('192.168.50.2', 161)),
            ContextData(),
            ObjectType(ObjectIdentity('1.3.6.1.2.1.1.5.0')))
print(next(it)[3])
PY
```

A returned `sysName` confirms the secondary connection. HSNC's poll loop will
then read live data over SNMPv3 for this device.
