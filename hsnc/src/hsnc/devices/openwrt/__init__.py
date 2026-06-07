"""OpenWrt-specific device code (gateways and access points).

Groups everything that is specific to OpenWrt-based devices in one place:

* :mod:`.adapter` — the SSH/UCI configuration adapter (primary connection).
* :mod:`.config_renderer` — renders a device into ``uci`` commands.
* :mod:`.ssh_monitoring` — primary runtime polling over SSH (``ubus``).
* :mod:`.prometheus_monitoring` — secondary runtime polling over a Prometheus
  node-exporter endpoint.
"""
