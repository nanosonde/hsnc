# Mock TP-Link JetStream switch (CLI over SSH)

A throwaway container that behaves like a TP-Link JetStream smart switch for the
sdn-manager switch adapter. It runs a real `sshd` whose login shell is a fake
JetStream CLI REPL backed by a persisted running/startup config.

This is a **device simulator**, not part of the application. The future real
`JetStreamCliAdapter` SSHes into it and drives the same CLI the `JetStreamCliRenderer`
emits.

## Build & run (standalone)

```sh
docker build -t mock-jetstream fakes/jetstream
docker run --rm -p 2202:22 --name mock-jetstream mock-jetstream
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
