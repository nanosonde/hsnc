"""OpenWrt-specific device code (gateways and access points).

Groups everything that is specific to OpenWrt-based devices in one place:

* :mod:`.adapter` — the SSH/UCI configuration adapter (config plane).
* :mod:`.config_renderer` — renders a device into ``uci`` commands.
* :mod:`.prometheus_monitoring` — runtime polling over a Prometheus
  node-exporter endpoint (monitoring plane).
"""
