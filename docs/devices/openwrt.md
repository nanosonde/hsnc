# OpenWrt device setup (gateway / access point)

OpenWrt devices are managed over SSH (configuration plane) and can optionally be
polled for live runtime data over a **Prometheus exporter** (secondary
monitoring plane).

## 1. Primary connection — SSH (required)

The configuration plane and the *primary* monitoring source both use SSH.

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

3. Inventory entry — primary polling needs no extra config:

   ```yaml
   - id: ap-1
     name: EAP245
     kind: access_point
     ip: 192.168.50.3
     connection:
       username: root
       port: 22
     monitoring:
       source: primary
   ```

## 2. Secondary connection — Prometheus exporter (optional)

To poll runtime data over Prometheus instead of SSH, install the node exporter
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

```yaml
- id: ap-1
  name: EAP245
  kind: access_point
  ip: 192.168.50.3
  connection:
    username: root
    port: 22
  monitoring:
    source: secondary
    secondary:
      type: prometheus
      endpoint: http://192.168.50.3:9100/metrics
```

If `endpoint` is omitted, HSNC derives `http://<device-ip>:9100/metrics`.

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

A `200` response with `node_*` metrics confirms the secondary connection. HSNC's
poll loop will then read live data from Prometheus for this device.
