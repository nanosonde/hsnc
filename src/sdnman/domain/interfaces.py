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
    """Talks to a real (or simulated) device to read and push *configuration*.

    This is the **configuration plane** and is SSH-only for real devices.
    Runtime/monitoring data lives behind :class:`MonitoringProvider` instead, so
    the two concerns can evolve independently (e.g. monitoring via a Prometheus
    exporter or SNMPv3 while configuration stays on SSH).

    Concrete adapters: MockDeviceAdapter, OpenWrtSshAdapter, JetStreamCliAdapter.
    """

    @abstractmethod
    def supports(self, device: Device) -> bool:
        """Return True if this adapter can manage the given device."""

    @abstractmethod
    def fetch_config(self, device: Device) -> Device:
        """Read the live configuration from the device.

        Returns a fully populated :class:`Device` reflecting the configuration
        currently running on the physical hardware, so it can be stored back
        into the declarative inventory.
        """

    @abstractmethod
    def push_config(self, device: Device) -> None:
        """Apply declarative configuration to the device (may be unimplemented)."""


class DeviceAdapterFactory(ABC):
    """Selects the appropriate :class:`DeviceAdapter` for a device."""

    @abstractmethod
    def for_device(self, device: Device) -> DeviceAdapter: ...


class MonitoringProvider(ABC):
    """Reads live runtime state (the **monitoring plane**) for a device.

    Decoupled from :class:`DeviceAdapter` (configuration) so monitoring can use a
    different transport than SSH. Implementations may scrape SSH (the fallback),
    an OpenWrt Prometheus exporter, SNMPv3 for switches, etc. When no monitoring
    source is available, :class:`NullMonitoringProvider` reports the device as
    ``DeviceStatus.UNKNOWN`` with no clients rather than inventing data.
    """

    @abstractmethod
    def fetch_status(self, device: Device) -> Device:
        """Return the device enriched with live runtime status.

        On an unreachable monitoring source, implementations should mark the
        device ``DeviceStatus.UNKNOWN`` (reachability unknown) rather than raise.
        """

    @abstractmethod
    def fetch_clients(self, device: Device) -> list[Client]:
        """Return clients currently observed on the device (may be empty)."""


class MonitoringProviderFactory(ABC):
    """Selects the appropriate :class:`MonitoringProvider` for a device."""

    @abstractmethod
    def for_device(self, device: Device) -> MonitoringProvider: ...


class DeviceConfigRenderer(ABC):
    """Renders a device's declarative config into platform-native commands.

    Implementations translate a :class:`Device` into the exact command sequence
    that would provision it on its platform (e.g. OpenWrt ``uci`` batches or the
    TP-Link JetStream CLI over SSH). This is what powers a command-level diff.
    """

    @property
    @abstractmethod
    def platform(self) -> str:
        """Human-readable platform label, e.g. ``"OpenWrt (UCI over SSH)"``."""

    @abstractmethod
    def render(self, device: Device) -> list[str]:
        """Return the ordered commands that realise ``device``'s configuration."""

    def settings(self, device: Device) -> dict[str, str]:
        """Return the device's config as flattened native ``path -> value`` pairs.

        For OpenWrt this mirrors LuCI's "Unsaved Changes" view, keyed by concrete
        UCI option paths (e.g. ``network.lan.ipaddr``). Platforms without a
        meaningful option-path representation return an empty mapping (default).
        """
        return {}


class DeviceConfigRendererFactory(ABC):
    """Selects the appropriate :class:`DeviceConfigRenderer` for a device."""

    @abstractmethod
    def for_device(self, device: Device) -> DeviceConfigRenderer: ...


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
    def prune(self, cutoff: datetime) -> int:
        """Delete runtime rows recorded before ``cutoff``; return rows removed."""

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

    @abstractmethod
    def delete_device(self, device_id: str) -> None:
        """Remove a single device from the inventory."""


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

    @abstractmethod
    def export_text(self) -> str:
        """Return the raw history (JSONL) for backups (empty if none)."""

    @abstractmethod
    def import_text(self, text: str) -> None:
        """Replace the history with the provided raw (JSONL) contents."""
