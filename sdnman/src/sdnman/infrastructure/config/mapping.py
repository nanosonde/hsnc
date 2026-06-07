"""Mapping between on-disk schemas and framework-free domain entities.

The device model is split across two stores:

* ``devices.yaml`` holds the **connection profile** (identity + how to reach the
  device): id, name, kind, site, SSH connection and the optional secondary
  monitoring channel. See :class:`~.schemas.DeviceSchema`.
* ``desired_config.json`` / ``current_config.json`` hold the **configuration
  payload** (VLANs, ports, SSIDs, firmware, …). See
  :class:`~.schemas.DeviceConfigSchema`.

A full :class:`Device` is assembled by merging a profile with its config
payload. These helpers centralise that translation so the repository and the
JSON stores never duplicate it.
"""

from __future__ import annotations

from ...domain.entities import (
    Device,
    DeviceConnection,
    MonitoringConfig,
    SwitchPort,
    Vlan,
)
from ...domain.enums import DeviceKind, DeviceStatus, PortMode
from ...domain.value_objects import IpAddress, MacAddress
from .schemas import (
    ConnectionSchema,
    DeviceConfigSchema,
    DeviceSchema,
    MonitoringSchema,
    PortSchema,
    VlanSchema,
)


def profile_to_device(schema: DeviceSchema) -> Device:
    """Build a :class:`Device` carrying only its connection profile."""

    connection = (
        DeviceConnection(
            host=schema.connection.host,
            port=schema.connection.port,
            username=schema.connection.username,
        )
        if schema.connection is not None
        else None
    )
    monitoring = (
        MonitoringConfig(type=schema.monitoring.type, endpoint=schema.monitoring.endpoint)
        if schema.monitoring is not None
        else None
    )
    return Device(
        id=schema.id,
        name=schema.name,
        kind=DeviceKind(schema.kind),
        ip=IpAddress(schema.ip) if schema.ip else None,
        status=DeviceStatus.UNKNOWN,
        site_id=schema.site_id,
        connection=connection,
        monitoring=monitoring,
    )


def device_to_profile(device: Device) -> DeviceSchema:
    """Extract the connection profile (``devices.yaml`` form) from a device."""

    return DeviceSchema(
        id=device.id,
        name=device.name,
        kind=device.kind.value,
        site_id=device.site_id,
        ip=str(device.ip) if device.ip else None,
        connection=(
            ConnectionSchema(
                host=device.connection.host,
                port=device.connection.port,
                username=device.connection.username,
            )
            if device.connection is not None
            else None
        ),
        monitoring=(
            MonitoringSchema(type=device.monitoring.type, endpoint=device.monitoring.endpoint)
            if device.monitoring is not None
            else None
        ),
    )


def device_to_config(device: Device) -> DeviceConfigSchema:
    """Extract the configuration payload (JSON-store form) from a device."""

    return DeviceConfigSchema(
        id=device.id,
        mac=str(device.mac) if device.mac else "",
        model=device.model,
        firmware=device.firmware,
        ports=[
            PortSchema(
                number=p.number,
                name=p.name,
                enabled=p.enabled,
                mode=p.mode.value,
                pvid=p.pvid,
                tagged_vlans=list(p.tagged_vlans),
            )
            for p in device.ports
        ],
        vlans=[VlanSchema(vlan_id=v.vlan_id, name=v.name, subnet=v.subnet) for v in device.vlans],
        ssids=list(device.ssids),
    )


def merge(profile: Device, config: DeviceConfigSchema | None) -> Device:
    """Overlay a configuration payload onto a connection profile.

    A profile without a config payload yields a device with empty configuration
    (no VLANs/ports/SSIDs), which is the expected state before the first read.
    """

    if config is None:
        return profile
    ports = [
        SwitchPort(
            number=p.number,
            name=p.name,
            enabled=p.enabled,
            mode=PortMode(p.mode),
            pvid=p.pvid,
            tagged_vlans=list(p.tagged_vlans),
        )
        for p in config.ports
    ]
    vlans = [Vlan(vlan_id=v.vlan_id, name=v.name, subnet=v.subnet) for v in config.vlans]
    from dataclasses import replace

    return replace(
        profile,
        mac=MacAddress(config.mac) if config.mac else None,
        model=config.model,
        firmware=config.firmware,
        ports=ports,
        vlans=vlans,
        ssids=list(config.ssids),
    )
