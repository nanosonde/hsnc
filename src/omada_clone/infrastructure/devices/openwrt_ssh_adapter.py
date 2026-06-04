"""OpenWrt device adapter (gateway / access point) over SSH + UCI.

Stub for the MVP: the seam exists so a real implementation using SSH and the
``uci``/``ubus`` tooling can drop in without touching the application or domain
layers. Methods raise :class:`NotImplementedError` until implemented.
"""

from __future__ import annotations

from ...domain.entities import Client, Device
from ...domain.enums import DeviceKind
from ...domain.interfaces import DeviceAdapter


class OpenWrtSshAdapter(DeviceAdapter):
    """Manages OpenWrt-based gateways and access points via SSH/UCI."""

    def __init__(self, ssh_user: str = "root", ssh_port: int = 22) -> None:
        self._user = ssh_user
        self._port = ssh_port

    def supports(self, device: Device) -> bool:
        return device.kind in (DeviceKind.GATEWAY, DeviceKind.ACCESS_POINT)

    def fetch_status(self, device: Device) -> Device:
        raise NotImplementedError(
            "OpenWrtSshAdapter.fetch_status is not implemented yet "
            "(planned: ubus call system board / network.interface status)."
        )

    def fetch_config(self, device: Device) -> Device:
        raise NotImplementedError(
            "OpenWrtSshAdapter.fetch_config is not implemented yet "
            "(planned: read uci network/wireless/system over SSH)."
        )

    def fetch_clients(self, device: Device) -> list[Client]:
        raise NotImplementedError(
            "OpenWrtSshAdapter.fetch_clients is not implemented yet "
            "(planned: ubus call iwinfo/dhcp leases)."
        )

    def push_config(self, device: Device) -> None:
        raise NotImplementedError(
            "OpenWrtSshAdapter.push_config is not implemented yet "
            "(planned: uci batch + commit over SSH)."
        )
