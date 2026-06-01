"""Abstract interfaces (ports) implemented by the infrastructure layer.

These define the contracts the application layer depends on, following the
Dependency Inversion Principle. No concrete I/O lives here.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Iterable
from datetime import datetime

from .entities import (
    ApplyEvent,
    AssociationFailure,
    Client,
    Device,
    Site,
    Topology,
    User,
)


class ConfigRepository(ABC):
    """Read/write access to declarative configuration (YAML-backed)."""

    @abstractmethod
    def get_site(self) -> Site: ...

    @abstractmethod
    def list_users(self) -> list[User]: ...

    @abstractmethod
    def get_user(self, username: str) -> User | None: ...

    @abstractmethod
    def list_devices(self) -> list[Device]: ...

    @abstractmethod
    def get_device(self, device_id: str) -> Device | None: ...


class DeviceAdapter(ABC):
    """Talks to a real (or simulated) device to read state / push config.

    Concrete adapters: MockDeviceAdapter, OpenWrtSshAdapter, JetStreamCliAdapter.
    """

    @abstractmethod
    def supports(self, device: Device) -> bool:
        """Return True if this adapter can manage the given device."""

    @abstractmethod
    def fetch_status(self, device: Device) -> Device:
        """Return the device enriched with live runtime status."""

    @abstractmethod
    def fetch_clients(self, device: Device) -> list[Client]:
        """Return clients currently associated with the device."""

    @abstractmethod
    def push_config(self, device: Device) -> None:
        """Apply declarative configuration to the device (may be unimplemented)."""


class DeviceAdapterFactory(ABC):
    """Selects the appropriate :class:`DeviceAdapter` for a device."""

    @abstractmethod
    def for_device(self, device: Device) -> DeviceAdapter: ...


class RuntimeStore(ABC):
    """Persistence for time-series runtime data (SQLite-backed)."""

    @abstractmethod
    def record_device_status(self, device: Device, at: datetime) -> None: ...

    @abstractmethod
    def record_client_session(self, client: Client, at: datetime) -> None: ...

    @abstractmethod
    def record_association_failures(
        self, failures: Iterable[AssociationFailure], at: datetime
    ) -> None: ...

    @abstractmethod
    def latest_association_failures(self) -> list[AssociationFailure]: ...

    @abstractmethod
    def export_rows(self) -> dict[str, list[dict]]:
        """Export all runtime tables as plain dict rows (for backups)."""

    @abstractmethod
    def import_rows(self, tables: dict[str, list[dict]]) -> None:
        """Replace runtime tables with the provided rows (for restores)."""


class TopologyProvider(ABC):
    """Builds the topology graph for a site."""

    @abstractmethod
    def build(self, devices: list[Device], clients: list[Client]) -> Topology: ...


class ConfigArchive(ABC):
    """Raw export/import of the declarative configuration for backups."""

    @abstractmethod
    def export_files(self) -> dict[str, str]:
        """Return a mapping of relative filename -> file contents."""

    @abstractmethod
    def import_files(self, files: dict[str, str]) -> None:
        """Replace configuration with the provided filename -> contents map."""


class ConfigWriter(ABC):
    """Persist declarative device configuration back to storage.

    Implementations validate the device, take a timestamped backup of the
    managed config files, then write atomically.
    """

    @abstractmethod
    def save_device(self, device: Device) -> None:
        """Create or update a single device in the inventory."""


class AppliedConfigStore(ABC):
    """Persists the last successfully applied configuration snapshot.

    The desired configuration lives in YAML; this store records what was last
    pushed to devices so a diff (pending changes) can be computed.
    """

    @abstractmethod
    def load(self) -> list[Device]:
        """Return the devices as of the last successful apply (may be empty)."""

    @abstractmethod
    def save(self, devices: list[Device]) -> None:
        """Replace the applied snapshot with the given devices."""


class ApplyHistoryStore(ABC):
    """Persists a log of configuration-apply runs for history / audit."""

    @abstractmethod
    def record_apply_event(self, event: ApplyEvent) -> None:
        """Append a single apply run to the history."""

    @abstractmethod
    def list_apply_events(self, limit: int = 50) -> list[ApplyEvent]:
        """Return the most recent apply runs, newest first."""
