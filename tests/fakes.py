"""In-memory fakes implementing the domain ports, for fast use-case tests."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from omada_clone.domain.entities import (
    AssociationFailure,
    Client,
    Device,
    Site,
    Topology,
    TopologyLink,
    TopologyNode,
    User,
)
from omada_clone.domain.interfaces import (
    ConfigRepository,
    DeviceAdapter,
    DeviceAdapterFactory,
    RuntimeStore,
    TopologyProvider,
)


class FakeConfigRepository(ConfigRepository):
    def __init__(self, site: Site, users: list[User], devices: list[Device]) -> None:
        self._site = site
        self._users = users
        self._devices = devices

    def get_site(self) -> Site:
        return self._site

    def list_users(self) -> list[User]:
        return list(self._users)

    def get_user(self, username: str) -> User | None:
        return next((u for u in self._users if u.username == username), None)

    def list_devices(self) -> list[Device]:
        return list(self._devices)

    def get_device(self, device_id: str) -> Device | None:
        return next((d for d in self._devices if d.id == device_id), None)


class FakeDeviceAdapter(DeviceAdapter):
    def __init__(self, clients_by_device: dict[str, list[Client]]) -> None:
        self._clients = clients_by_device

    def supports(self, device: Device) -> bool:
        return True

    def fetch_status(self, device: Device) -> Device:
        return device

    def fetch_clients(self, device: Device) -> list[Client]:
        return list(self._clients.get(device.id, []))

    def push_config(self, device: Device) -> None:
        return None


class FakeAdapterFactory(DeviceAdapterFactory):
    def __init__(self, adapter: DeviceAdapter) -> None:
        self._adapter = adapter

    def for_device(self, device: Device) -> DeviceAdapter:
        return self._adapter


class FakeRuntimeStore(RuntimeStore):
    def __init__(self) -> None:
        self.device_status: list[tuple[str, str]] = []
        self.client_sessions: list[tuple[str, str]] = []
        self.failures: list[AssociationFailure] = []

    def record_device_status(self, device: Device, at: datetime) -> None:
        self.device_status.append((device.id, at.isoformat()))

    def record_client_session(self, client: Client, at: datetime) -> None:
        self.client_sessions.append((client.id, at.isoformat()))

    def record_association_failures(
        self, failures: Iterable[AssociationFailure], at: datetime
    ) -> None:
        self.failures = list(failures)

    def latest_association_failures(self) -> list[AssociationFailure]:
        return list(self.failures)

    def export_rows(self) -> dict[str, list[dict]]:
        return {}

    def import_rows(self, tables: dict[str, list[dict]]) -> None:
        return None


class FakeTopologyProvider(TopologyProvider):
    def build(self, devices: list[Device], clients: list[Client]) -> Topology:
        nodes = [TopologyNode("internet", "Internet", "internet")]
        links = []
        for device in devices:
            nodes.append(TopologyNode(device.id, device.name, "device"))
            links.append(TopologyLink("internet", device.id))
        return Topology(nodes=nodes, links=links)
