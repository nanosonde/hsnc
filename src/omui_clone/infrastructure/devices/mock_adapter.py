"""In-memory mock device adapter producing realistic demo data.

Generates deterministic data that mirrors the reference screenshots: a single
JetStream switch with six wired LAN clients, an OpenWrt access point and an
OpenWrt gateway. Used for the MVP and for tests/local development.
"""

from __future__ import annotations

from ...domain.entities import Client, Device
from ...domain.enums import ConnectionType, DeviceStatus
from ...domain.interfaces import DeviceAdapter
from ...domain.value_objects import DataVolume, IpAddress, MacAddress, Throughput

# Demo clients keyed by the device they are attached to. Mirrors the
# "All (6)" wired-clients list from the reference screenshot.
_DEMO_CLIENTS: dict[str, list[dict]] = {
    "switch-1": [
        {"id": "c1", "name": "D4-5D", "mac": "D4:5D:64:11:22:33",
         "ip": "192.168.50.1", "uptime": 1618},
        {"id": "c2", "name": "DESKTOP-5DO0R", "mac": "AC:1F:6B:00:00:01",
         "ip": None, "uptime": 1588},
        {"id": "c3", "name": "Galaxy-A51-dl-Lac", "mac": "AC:1F:6B:00:00:02",
         "ip": None, "uptime": 372},
        {"id": "c4", "name": "IsiPhone", "mac": "AC:1F:6B:00:00:03",
         "ip": None, "uptime": 1277},
        {"id": "c5", "name": "OC200_E491B4", "mac": "B0:4E:26:E4:91:B4",
         "ip": "192.168.50.197", "uptime": 1591},
        {"id": "c6", "name": "Sweeper", "mac": "AC:1F:6B:00:00:05",
         "ip": None, "uptime": 1609},
    ],
}

# Live status overrides applied on top of the declarative device definition.
_DEMO_STATUS: dict[str, dict] = {
    "gateway-1": {"status": DeviceStatus.DISCONNECTED, "uptime": 0},
    "switch-1": {"status": DeviceStatus.CONNECTED, "uptime": 1602},
    "ap-1": {"status": DeviceStatus.CONNECTED, "uptime": 1600},
}


class MockDeviceAdapter(DeviceAdapter):
    """Returns canned-but-plausible data for any device."""

    def supports(self, device: Device) -> bool:  # noqa: D102 - manages all devices
        return True

    def fetch_status(self, device: Device) -> Device:
        override = _DEMO_STATUS.get(device.id)
        if override:
            device.status = override["status"]
            device.uptime_seconds = override["uptime"]
        else:
            device.status = DeviceStatus.CONNECTED
        return device

    def fetch_config(self, device: Device) -> Device:
        # The mock has no separate source of truth, so a re-read simply returns
        # the device enriched with its live status, demonstrating the flow.
        return self.fetch_status(device)

    def fetch_clients(self, device: Device) -> list[Client]:
        clients: list[Client] = []
        for spec in _DEMO_CLIENTS.get(device.id, []):
            clients.append(
                Client(
                    id=spec["id"],
                    name=spec["name"],
                    mac=MacAddress(spec["mac"]),
                    connection=ConnectionType.WIRED,
                    status=DeviceStatus.CONNECTED,
                    ip=IpAddress(spec["ip"]) if spec["ip"] else None,
                    network="LAN",
                    ssid="",
                    ap_or_port=device.name,
                    activity=Throughput(0),
                    downloaded=DataVolume(0),
                    uploaded=DataVolume(0),
                    uptime_seconds=spec["uptime"],
                    site_id=device.site_id,
                )
            )
        return clients

    def push_config(self, device: Device) -> None:
        # Mock adapter accepts config silently; nothing to apply.
        return None
