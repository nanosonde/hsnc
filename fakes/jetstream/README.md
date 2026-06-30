# Mock TP-Link JetStream switch (CLI over SSH; SNMPv3 monitoring)

A throwaway container that behaves like a TP-Link JetStream smart switch for the
hsnc switch drivers. It serves **both planes**: a real `sshd` whose login shell is
a fake JetStream CLI REPL (the **configuration plane**), and an `snmpd` SNMPv3
agent on UDP `161` (the **monitoring plane**, never SSH).

This is a **device simulator**, not part of the application. The real
`JetStreamCliAdapter` SSHes into it and drives the same CLI the `JetStreamCliRenderer`
emits; the real `JetStreamSnmpMonitoringProvider` polls it over SNMPv3.

## Build & run (standalone)

```sh
docker build -t mock-jetstream fakes/jetstream
docker run --rm -p 2202:22 -p 1161:161/udp --name mock-jetstream mock-jetstream
```

Or via the bundled compose file (recommended): see `fakes/README.md`.

## Connect

```sh
ssh -p 2202 admin@localhost          # password: admin (default)
```

The CLI is the login shell, so you land directly at the `TL-SG2210P>` prompt. It
also handles non-interactive use:

```sh
ssh -p 2202 admin@localhost "show running-config"
printf 'enable\nconfigure\nvlan 99\nname lab\nend\nshow running-config\n' \
  | ssh -p 2202 admin@localhost
```

Credentials come from env: `MOCK_SSH_USER` (default `admin`), `MOCK_SSH_PASSWORD`
(default `admin`), optional `MOCK_SSH_PUBKEY`.

## Emulated commands

Config mode:

| Command | Effect |
| --- | --- |
| `enable` / `configure[ terminal]` | enter privileged / config mode (auto-enable) |
| `hostname <name>` | rename the switch (changes the prompt) |
| `vlan <id>` / `name <text>` / `exit` | create/select a VLAN and name it |
| `interface gigabitEthernet 1/0/<n>` | select a port |
| `switchport mode access\|trunk\|general\|hybrid` | set port mode (the controller models only `access`/`trunk`/`hybrid`; a port read back in `general` mode is reported as `trunk`) |
| `switchport access vlan <id>` | access VLAN (also sets pvid) |
| `switchport general allowed vlan 1,10,20` | tagged/allowed VLAN set |
| `switchport pvid <id>` | set native/PVID |
| `shutdown` / `no shutdown` | disable/enable the port |
| `end` | return to privileged mode |
| `copy running-config startup-config` | persist startup config (survives restart) |

Show commands: `show running-config`, `show system-info`, `show interface status`,
`show mac address-table`, `show vlan`.

## Monitoring plane (SNMPv3, never SSH)

`snmpd` listens on UDP `161` (host `1161`) as an SNMPv3 USM agent (`authPriv`,
SHA auth + AES priv) and answers exactly what the
`JetStreamSnmpMonitoringProvider` queries:

| OID | Object | Source |
| --- | --- | --- |
| `1.3.6.1.2.1.1.1.0` | `sysDescr` | `MOCK_MODEL` (device model) |
| `1.3.6.1.2.1.1.3.0` | `sysUpTime` | agent uptime |
| `1.3.6.1.2.1.1.5.0` | `sysName` | switch hostname (from `running.json`) |
| `1.3.6.1.2.1.17.4.3.1.2` | `dot1dTpFdbPort` | MAC table (mirrors `show mac address-table`) |

The USM user is created on first boot from `MOCK_SNMP_USER` /
`MOCK_SNMP_AUTH_KEY` / `MOCK_SNMP_PRIV_KEY` (defaults `hsncmon` / `hsncauth123`
/ `hsncpriv123`); the controller must match them via `HSNC_SNMP_USER` /
`HSNC_SNMP_AUTH_KEY` / `HSNC_SNMP_PRIV_KEY`.

```sh
docker exec mock-jetstream snmpget -v3 -l authPriv -u hsncmon \
  -a SHA -A hsncauth123 -x AES -X hsncpriv123 localhost 1.3.6.1.2.1.1.1.0
docker exec mock-jetstream snmpwalk -v3 -l authPriv -u hsncmon \
  -a SHA -A hsncauth123 -x AES -X hsncpriv123 localhost 1.3.6.1.2.1.17.4.3.1.2
```

## State, seeding & reset

State lives at `$MOCK_STATE_DIR` (default `/var/lib/mockdev`):

- `running.json` — live config (updated on every change)
- `startup.json` — persisted by `copy running-config startup-config`; loaded on boot

On first boot the seed `seed/running.json` is copied into the (empty) state volume
and duplicated as the startup config. To reset:

```sh
docker exec mock-jetstream rm -f /var/lib/mockdev/running.json /var/lib/mockdev/startup.json
docker restart mock-jetstream
```

## Quick check

```sh
ssh -p 2202 admin@localhost "show running-config"
```
