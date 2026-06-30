# OpenWrt device setup (gateway / access point)

OpenWrt devices are configured over SSH (configuration plane) and polled for live
runtime data over a **Prometheus exporter** (monitoring plane). The monitoring
plane never uses SSH.

## 1. SSH — configuration plane (required)

SSH is used only for reading and pushing configuration (`uci`).

1. Install and enable the SSH server (`dropbear` ships by default on OpenWrt):

   ```sh
   uci set dropbear.@dropbear[0].PasswordAuth='on'
   uci set dropbear.@dropbear[0].Port='22'
   uci commit dropbear
   /etc/init.d/dropbear restart
   ```

2. Set a root password on the device (`passwd`), then provide it to HSNC via the
   environment — never in `devices.yaml`:

   ```sh
   # global default for all OpenWrt devices
   HSNC_OPENWRT_SSH_PASSWORD=...
   # or per device (id upper-cased, non-alphanumerics -> _)
   HSNC_DEVICE_AP_1_PASSWORD=...
   ```

3. Inventory entry — the SSH connection profile:

   ```yaml
   - id: ap-1
     name: EAP245
     kind: access_point
     ip: 192.168.50.3
     connection:
       username: root
       port: 22
     monitoring:
       enabled: true
   ```

## 2. Prometheus exporter — monitoring plane (required)

Live runtime data is read over Prometheus, never SSH. Install the node exporter
on the OpenWrt device and point HSNC at its `/metrics` endpoint.

### Install the exporter

```sh
opkg update
opkg install prometheus-node-exporter-lua
# wifi station metrics (needed for the connected-clients list):
opkg install prometheus-node-exporter-lua-wifi_stations
```

Configure and start it (listens on TCP/9100 by default):

```sh
uci set prometheus-node-exporter-lua.main.listen_interface='lan'
uci set prometheus-node-exporter-lua.main.listen_ipv6='0'
uci commit prometheus-node-exporter-lua
/etc/init.d/prometheus-node-exporter-lua enable
/etc/init.d/prometheus-node-exporter-lua restart
```

### Open the firewall to the controller

Allow the HSNC host to reach TCP/9100 on the `lan` zone (adjust the source as
needed):

```sh
uci add firewall rule
uci set firewall.@rule[-1].name='Allow-Prometheus'
uci set firewall.@rule[-1].src='lan'
uci set firewall.@rule[-1].proto='tcp'
uci set firewall.@rule[-1].dest_port='9100'
uci set firewall.@rule[-1].target='ACCEPT'
uci commit firewall
/etc/init.d/firewall restart
```

### Point HSNC at the exporter

By default HSNC derives `http://<device-ip>:9100/metrics`, so no `monitoring`
block is required. Override the endpoint only if the exporter answers elsewhere:

```yaml
- id: ap-1
  name: EAP245
  kind: access_point
  ip: 192.168.50.3
  connection:
    username: root
    port: 22
  monitoring:
    enabled: true
    endpoint: http://192.168.50.3:9100/metrics
```

Set `enabled: false` to disable polling for a device (it then reports
`unknown`).

### Optional: bearer token

If you front the exporter with an authenticating proxy, supply the token via the
environment (never in `devices.yaml`):

```sh
HSNC_PROMETHEUS_TOKEN=...                  # global default
HSNC_DEVICE_AP_1_PROMETHEUS_TOKEN=...      # per device
HSNC_PROMETHEUS_VERIFY_TLS=1               # set 0 to skip TLS verification
```

### What HSNC reads

| Data | Metrics used |
| --- | --- |
| Reachability | a successful scrape -> `connected` |
| Uptime | `node_time_seconds - node_boot_time_seconds` (or `node_uptime_seconds`) |
| Model / firmware | `node_uname_info{machine=...,release=...}` |
| Clients | any sample carrying a `mac` label (e.g. `wifi_station_*`); the `ifname`/`vap` label becomes the port/AP |

If the wifi-stations collector is not installed, status/uptime still work but no
clients are listed.

## 3. Verify

```sh
# From the HSNC host (curl may be unavailable; Python works everywhere):
python3 -c "import urllib.request as u; print(u.urlopen('http://192.168.50.3:9100/metrics', timeout=5).read()[:200])"
```

A `200` response with `node_*` metrics confirms the monitoring connection. HSNC's
poll loop will then read live data from Prometheus for this device.
