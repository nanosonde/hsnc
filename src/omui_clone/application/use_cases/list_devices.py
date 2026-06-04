"""Use cases: list devices and fetch a single device's detail."""

from __future__ import annotations

from ...domain.entities import Device
from ..dtos import DeviceDetail, DeviceRow, PortRow, VlanRow
from ..formatters import humanize_uptime
from ..services import NetworkStateService


def _to_row(device: Device, client_count: int = 0) -> DeviceRow:
    return DeviceRow(
        id=device.id,
        name=device.name,
        kind=device.kind.value,
        model=device.model,
        mac=str(device.mac),
        ip=str(device.ip) if device.ip else "-",
        status=device.status.value,
        firmware=device.firmware,
        uptime=humanize_uptime(device.uptime_seconds),
        client_count=client_count,
    )


class ListDevices:
    """Return all managed devices with their live status."""

    def __init__(self, network: NetworkStateService) -> None:
        self._network = network

    def execute(self) -> list[DeviceRow]:
        devices = self._network.devices()
        rows: list[DeviceRow] = []
        for device in devices:
            clients = self._network.clients_for(device)
            rows.append(_to_row(device, len(clients)))
        return rows


class GetDeviceDetail:
    """Return a single device with port/VLAN/SSID detail."""

    def __init__(self, network: NetworkStateService) -> None:
        self._network = network

    def execute(self, device_id: str) -> DeviceDetail | None:
        for device in self._network.devices():
            if device.id != device_id:
                continue
            clients = self._network.clients_for(device)
            ports = [
                PortRow(
                    number=p.number,
                    name=p.name,
                    enabled=p.enabled,
                    mode=p.mode.value,
                    pvid=p.pvid,
                    tagged_vlans=list(p.tagged_vlans),
                    link_up=p.link_up,
                    speed_mbps=p.speed_mbps,
                )
                for p in device.ports
            ]
            vlans = [VlanRow(v.vlan_id, v.name, v.subnet) for v in device.vlans]
            return DeviceDetail(
                row=_to_row(device, len(clients)),
                ports=ports,
                vlans=vlans,
                ssids=list(device.ssids),
            )
        return None
