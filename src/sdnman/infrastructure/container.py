"""Composition root: wires concrete infrastructure into application use cases.

This is the only place where concrete classes are instantiated and bound to the
abstract ports. The presentation layer asks the container for ready-to-use use
cases, keeping framework code free of construction logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from ..application.services import NetworkStateService
from ..application.use_cases.apply_config import ApplyConfig, PlanApply
from ..application.use_cases.apply_history import ListApplyHistory
from ..application.use_cases.authenticate_user import AuthenticateUser
from ..application.use_cases.backup import ExportBackup, ImportBackup
from ..application.use_cases.config_diff import GetConfigDiff
from ..application.use_cases.delete_device import DeleteDevice
from ..application.use_cases.edit_device_config import (
    DeleteVlan,
    SavePort,
    SaveSsids,
    SaveVlan,
)
from ..application.use_cases.get_dashboard_summary import GetDashboardSummary
from ..application.use_cases.get_topology import GetTopology
from ..application.use_cases.list_clients import ListClients
from ..application.use_cases.list_devices import GetDeviceDetail, ListDevices
from ..application.use_cases.poll_device_state import PollDeviceState
from ..application.use_cases.revert_config import RevertPendingChanges
from ..application.use_cases.sync_device_config import SyncDeviceConfig
from .config.applied_config_store import FileAppliedConfigStore
from .config.yaml_config_repository import YamlConfigRepository
from .devices.config_renderers import DefaultConfigRendererFactory
from .devices.factory import DefaultDeviceAdapterFactory
from .devices.monitoring import DefaultMonitoringProviderFactory
from .devices.ssh_transport import SshConnectionResolver, SshConnectionSettings
from .devices.topology_provider import SimpleTopologyProvider
from .persistence.jsonl_apply_history_store import JsonlApplyHistoryStore
from .persistence.sqlite_runtime_store import SqliteRuntimeStore
from .security import verify_password


@dataclass
class Settings:
    """Runtime configuration resolved from environment/defaults."""

    config_dir: Path
    data_dir: Path
    use_mock_devices: bool = True
    poll_interval_seconds: int = 30
    retention_days: int = 30
    monitor_cache_ttl_seconds: int = 30
    ssh: SshConnectionSettings = field(default_factory=SshConnectionSettings)

    @property
    def runtime_db_path(self) -> Path:
        return self.data_dir / "runtime.db"

    @property
    def history_path(self) -> Path:
        return self.data_dir / "history.jsonl"

    @property
    def config_backup_dir(self) -> Path:
        return self.data_dir / "config-backups"


class Container:
    """Holds singletons and exposes constructed use cases."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        # adapters / repositories (singletons)
        self.config = YamlConfigRepository(
            settings.config_dir, backup_dir=settings.config_backup_dir
        )
        self.runtime = SqliteRuntimeStore(settings.runtime_db_path)
        self.history = JsonlApplyHistoryStore(settings.history_path)
        self.adapters = DefaultDeviceAdapterFactory(
            use_mock=settings.use_mock_devices,
            resolver=SshConnectionResolver(settings.ssh),
        )
        self.monitoring = DefaultMonitoringProviderFactory(
            use_mock=settings.use_mock_devices,
            resolver=SshConnectionResolver(settings.ssh),
        )
        self.renderers = DefaultConfigRendererFactory()
        self.topology_provider = SimpleTopologyProvider()
        self.applied_config = FileAppliedConfigStore(settings.data_dir)

        # application services. The poller scrapes fresh every cycle (records the
        # time-series), so it uses an uncached view. Web reads use a short-TTL
        # cache so browsing does not re-SSH every device on each page load.
        self.network = NetworkStateService(self.config, self.monitoring)
        self.network_cached = NetworkStateService(
            self.config,
            self.monitoring,
            cache_ttl_seconds=settings.monitor_cache_ttl_seconds,
        )

        # use cases
        self.authenticate_user = AuthenticateUser(self.config, verify_password)
        self.get_dashboard_summary = GetDashboardSummary(
            self.config, self.network_cached, self.runtime
        )
        self.list_devices = ListDevices(self.network_cached)
        self.get_device_detail = GetDeviceDetail(self.network_cached)
        self.list_clients = ListClients(self.network_cached)
        self.get_topology = GetTopology(self.network_cached, self.topology_provider)
        self.poll_device_state = PollDeviceState(
            self.network, self.runtime, retention_days=settings.retention_days
        )
        self.export_backup = ExportBackup(self.config, self.runtime, self.history)
        self.import_backup = ImportBackup(self.config, self.runtime, self.history)

        # configuration management use cases
        self.save_vlan = SaveVlan(self.config, self.config)
        self.delete_vlan = DeleteVlan(self.config, self.config)
        self.save_port = SavePort(self.config, self.config)
        self.save_ssids = SaveSsids(self.config, self.config)
        self.get_config_diff = GetConfigDiff(
            self.config, self.applied_config, self.renderers
        )
        self.plan_apply = PlanApply(self.config, self.applied_config, self.adapters)
        self.apply_config = ApplyConfig(
            self.config, self.adapters, self.applied_config, self.history
        )
        self.list_apply_history = ListApplyHistory(self.history)
        self.revert_changes = RevertPendingChanges(
            self.config, self.applied_config, self.config
        )
        self.sync_device_config = SyncDeviceConfig(
            self.config,
            self.adapters,
            self.config,
            self.applied_config,
            self.history,
        )
        self.delete_device = DeleteDevice(self.config, self.applied_config)

    def close(self) -> None:
        self.runtime.close()
        self.history.close()
