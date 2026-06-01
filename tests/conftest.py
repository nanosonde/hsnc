"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from omada_clone.domain.entities import Client, Device, Site, User
from omada_clone.domain.enums import (
    ConnectionType,
    DeviceKind,
    DeviceStatus,
    Role,
)
from omada_clone.domain.value_objects import (
    DataVolume,
    IpAddress,
    MacAddress,
    Throughput,
)

from .fakes import (
    FakeAdapterFactory,
    FakeConfigRepository,
    FakeDeviceAdapter,
)


@pytest.fixture
def site() -> Site:
    return Site(id="default", name="Default", country="DE")


@pytest.fixture
def users() -> list[User]:
    return [
        User("admin", "hash-admin", Role.ADMIN, "Administrator"),
        User("viewer", "hash-viewer", Role.VIEWER, "Read Only"),
    ]


@pytest.fixture
def devices() -> list[Device]:
    return [
        Device(
            id="switch-1",
            name="TL-SG2210P",
            kind=DeviceKind.SWITCH,
            mac=MacAddress("B0:4E:26:00:00:10"),
            ip=IpAddress("192.168.50.2"),
            status=DeviceStatus.CONNECTED,
        ),
        Device(
            id="gateway-1",
            name="ER605",
            kind=DeviceKind.GATEWAY,
            mac=MacAddress("AC:1F:6B:A0:00:01"),
            status=DeviceStatus.DISCONNECTED,
        ),
    ]


@pytest.fixture
def clients() -> list[Client]:
    return [
        Client(
            id=f"c{i}",
            name=f"client-{i}",
            mac=MacAddress(f"AC:1F:6B:00:00:0{i}"),
            connection=ConnectionType.WIRED,
            status=DeviceStatus.CONNECTED,
            ip=IpAddress(f"192.168.50.{10 + i}"),
            network="LAN",
            activity=Throughput(0),
            downloaded=DataVolume(1024 * i),
            uploaded=DataVolume(512 * i),
            uptime_seconds=60 * i,
        )
        for i in range(1, 7)
    ]


@pytest.fixture
def config(site, users, devices) -> FakeConfigRepository:
    return FakeConfigRepository(site, users, devices)


@pytest.fixture
def adapters(clients) -> FakeAdapterFactory:
    # all clients attached to switch-1
    adapter = FakeDeviceAdapter({"switch-1": clients})
    return FakeAdapterFactory(adapter)
