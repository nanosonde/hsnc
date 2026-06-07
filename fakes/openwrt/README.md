# Mock OpenWrt device (UCI + ubus over SSH)

A throwaway container that behaves like an OpenWrt router/AP for the purposes of the
sdn-manager OpenWrt SSH adapter. It runs a real `sshd` whose shell has fake `uci` and
`ubus` commands on `PATH`, backed by a persisted UCI state file.

This is a **device simulator**, not part of the application. The real
`OpenWrtSshAdapter` SSHes into it and runs the same `uci`/`ubus` commands the
`UciConfigRenderer` emits.

## Build & run (standalone)

```sh
docker build -t mock-openwrt fakes/openwrt
docker run --rm -p 2201:22 --name mock-openwrt mock-openwrt
```

Or via the bundled compose file (recommended): see `fakes/README.md`.

## Connect

```sh
ssh -p 2201 root@localhost          # password: openwrt (default)
```

Credentials come from env: `MOCK_SSH_USER` (default `root`), `MOCK_SSH_PASSWORD`
(default `openwrt`), and optional `MOCK_SSH_PUBKEY` for key auth.

## Emulated commands

| Command | Notes |
| --- | --- |
| `uci show [<pkg>[.<sec>[.<opt>]]]` | dump state in canonical `uci show` form |
| `uci get <pkg>.<sec>.<opt>` | print a single value |
| `uci set <pkg>.<sec>=<type>` / `...<opt>=<val>` | create/update section or option |
| `uci add <pkg> <type>` | add anonymous section, prints `@type[idx]` |
| `uci add_list <pkg>.<sec>.<opt>=<val>` | append to a list option |
| `uci delete <pkg>.<sec>[.<opt>]` | remove section or option |
| `uci commit [<pkg>]` | no-op success (state persists on every write) |
| `uci batch` | run the above, one per line, from stdin |
| `ubus call system board` | JSON: model, hostname, kernel, release |
| `ubus call network.interface.<name> status` | JSON: up + ipv4 (live from uci) |
| `ubus call iwinfo assoclist '{"device":"wlan0"}'` | associated wifi clients |
| `ubus call dhcp ipv4leases` | DHCP leases (from the leases file) |

Anonymous sections support both positive and negative indices, e.g.
`network.@bridge-vlan[-1]` references the most recently added bridge-vlan — exactly
what the renderer uses after `uci add network bridge-vlan`.

## State, seeding & reset

State lives at `$MOCK_STATE_DIR` (default `/var/lib/mockdev`):

- `uci.conf` — UCI state in `uci show` format
- `dhcp.leases` — dnsmasq-style leases

On first boot the seed under `seed/` is copied into the (empty) state volume. To
re-seed, delete the files and restart:

```sh
docker exec mock-openwrt rm -f /var/lib/mockdev/uci.conf /var/lib/mockdev/dhcp.leases
docker restart mock-openwrt
```

## Quick check

```sh
ssh -p 2201 root@localhost 'ubus call system board'
ssh -p 2201 root@localhost \
  'uci set network.lan.ipaddr=10.0.0.1; uci commit; uci get network.lan.ipaddr'
```
