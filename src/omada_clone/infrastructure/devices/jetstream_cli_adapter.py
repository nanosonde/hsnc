"""TP-Link JetStream managed-switch adapter over SSH/CLI.

Stub for the MVP: the seam exists so a real implementation using the JetStream
CLI (VLAN, port config, status) can drop in later. Methods raise
:class:`NotImplementedError` until implemented.
"""

from __future__ import annotations

from ...domain.entities import Client, Device
from ...domain.enums import DeviceKind
from ...domain.interfaces import DeviceAdapter


class JetStreamCliAdapter(DeviceAdapter):
    """Manages TP-Link JetStream switches via the SSH command-line interface."""

    def __init__(self, ssh_user: str = "admin", ssh_port: int = 22) -> None:
        self._user = ssh_user
        self._port = ssh_port

    def supports(self, device: Device) -> bool:
        return device.kind is DeviceKind.SWITCH

    def fetch_status(self, device: Device) -> Device:
        raise NotImplementedError(
            "JetStreamCliAdapter.fetch_status is not implemented yet "
            "(planned: 'show system-info' / 'show interface status')."
        )

    def fetch_clients(self, device: Device) -> list[Client]:
        raise NotImplementedError(
            "JetStreamCliAdapter.fetch_clients is not implemented yet "
            "(planned: 'show mac address-table')."
        )

    def push_config(self, device: Device) -> None:
        raise NotImplementedError(
            "JetStreamCliAdapter.push_config is not implemented yet "
            "(planned: VLAN/port CLI configuration over SSH)."
        )
