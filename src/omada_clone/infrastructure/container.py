"""Composition root: wires concrete infrastructure into application use cases.

This is the only place where concrete classes are instantiated and bound to the
abstract ports. The presentation layer asks the container for ready-to-use use
cases, keeping framework code free of construction logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..application.services import NetworkStateService
from ..application.use_cases.authenticate_user import AuthenticateUser
from ..application.use_cases.backup import ExportBackup, ImportBackup
from ..application.use_cases.get_dashboard_summary import GetDashboardSummary
from ..application.use_cases.get_topology import GetTopology
from ..application.use_cases.list_clients import ListClients
from ..application.use_cases.list_devices import GetDeviceDetail, ListDevices
from ..application.use_cases.poll_device_state import PollDeviceState
from .config.yaml_config_repository import YamlConfigRepository
from .devices.factory import DefaultDeviceAdapterFactory
from .devices.topology_provider import SimpleTopologyProvider
from .persistence.sqlite_runtime_store import SqliteRuntimeStore
from .security import verify_password


@dataclass
class Settings:
    """Runtime configuration resolved from environment/defaults."""

    config_dir: Path
    data_dir: Path
    use_mock_devices: bool = True
    poll_interval_seconds: int = 30

    @property
    def db_path(self) -> Path:
        return self.data_dir / "runtime.db"


class Container:
    """Holds singletons and exposes constructed use cases."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        # adapters / repositories (singletons)
        self.config = YamlConfigRepository(settings.config_dir)
        self.runtime = SqliteRuntimeStore(settings.db_path)
        self.adapters = DefaultDeviceAdapterFactory(use_mock=settings.use_mock_devices)
        self.topology_provider = SimpleTopologyProvider()

        # application services
        self.network = NetworkStateService(self.config, self.adapters)

        # use cases
        self.authenticate_user = AuthenticateUser(self.config, verify_password)
        self.get_dashboard_summary = GetDashboardSummary(
            self.config, self.network, self.runtime
        )
        self.list_devices = ListDevices(self.network)
        self.get_device_detail = GetDeviceDetail(self.network)
        self.list_clients = ListClients(self.network)
        self.get_topology = GetTopology(self.network, self.topology_provider)
        self.poll_device_state = PollDeviceState(self.network, self.runtime)
        self.export_backup = ExportBackup(self.config, self.runtime)
        self.import_backup = ImportBackup(self.config, self.runtime)

    def close(self) -> None:
        self.runtime.close()
