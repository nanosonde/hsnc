"""Composition root: wires concrete adapters into the application use cases.

This is the only place where concrete classes are instantiated and bound to the
abstract ports. The backend delivery layer asks the container for ready-to-use
use cases, keeping framework code free of construction logic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from .config.applied_config_store import CurrentConfigStore
from .config.device_config_store import JsonDeviceConfigStore
from .config.layered_config_repository import LayeredConfigRepository
from .config.yaml_config_repository import YamlConfigRepository
from .devices.config_renderers import DefaultConfigRendererFactory
from .devices.factory import DefaultDeviceAdapterFactory
from .devices.monitoring import DefaultMonitoringProviderFactory
from .devices.runtime_monitoring import RuntimeStoreMonitoringFactory
from .devices.ssh_transport import (
    PersistentRunnerRegistry,
    SshConnectionResolver,
    SshConnectionSettings,
)
from .devices.topology_provider import SimpleTopologyProvider
from .persistence.jsonl_apply_history_store import JsonlApplyHistoryStore
from .persistence.sqlite_runtime_store import SqliteRuntimeStore
from .security import verify_password
from .services import NetworkStateService
from .use_cases.apply_config import ApplyConfig, PlanApply
from .use_cases.apply_history import ListApplyHistory
from .use_cases.authenticate_user import AuthenticateUser
from .use_cases.backup import ExportBackup, ImportBackup
from .use_cases.baseline import ReadBaseline
from .use_cases.config_diff import GetConfigDiff
from .use_cases.delete_device import DeleteDevice
from .use_cases.edit_device_config import (
    DeleteVlan,
    SavePort,
    SaveSsids,
    SaveVlan,
)
from .use_cases.get_dashboard_summary import GetDashboardSummary
from .use_cases.get_topology import GetTopology
from .use_cases.list_clients import ListClients
from .use_cases.list_devices import GetDeviceDetail, ListDevices
from .use_cases.poll_device_state import PollDeviceState
from .use_cases.revert_config import RevertPendingChanges
from .use_cases.sync_device_config import SyncDeviceConfig


@dataclass
class Settings:
    """Runtime configuration resolved from environment/defaults."""

    config_dir: Path
    data_dir: Path
    use_mock_devices: bool = True
    poll_interval_seconds: int = 30
    retention_days: int = 30
    baseline_on_start: bool = True
    ssh: SshConnectionSettings = field(default_factory=SshConnectionSettings)

    @property
    def runtime_db_path(self) -> Path:
        return self.data_dir / "runtime.db"

    @property
    def history_path(self) -> Path:
        return self.data_dir / "history.jsonl"

    @property
    def desired_config_path(self) -> Path:
        return self.data_dir / "desired_config.json"

    @property
    def current_config_path(self) -> Path:
        return self.data_dir / "current_config.json"

    @property
    def config_backup_dir(self) -> Path:
        return self.data_dir / "config-backups"


class Container:
    """Holds singletons and exposes constructed use cases.

    Real SSH adapters perform configuration I/O (apply/sync/baseline) and a
    background poll loop scrapes live monitoring into the runtime store. Read
    use cases serve the latest snapshot from that store, so a read request never
    opens a device connection.
    """

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

        # configuration: connection profiles (devices.yaml) + config payloads
        # (desired_config.json edited by the UI, current_config.json = baseline).
        self.profiles = YamlConfigRepository(
            settings.config_dir, backup_dir=settings.config_backup_dir
        )
        self.desired_store = JsonDeviceConfigStore(settings.desired_config_path)
        self.current_store = JsonDeviceConfigStore(settings.current_config_path)
        self.config = LayeredConfigRepository(
            self.profiles, self.desired_store, self.current_store
        )
        self.runtime = SqliteRuntimeStore(settings.runtime_db_path)
        self.history = JsonlApplyHistoryStore(settings.history_path)
        self.renderers = DefaultConfigRendererFactory()
        self.topology_provider = SimpleTopologyProvider()
        self.applied_config = CurrentConfigStore(
            settings.data_dir, self.profiles, store=self.current_store
        )

        # connection-plane + monitoring-plane wiring. Real SSH adapters own all
        # device I/O; read endpoints serve the latest runtime snapshot, kept
        # fresh by the poll loop scraping live monitoring.
        self.ssh_resolver = SshConnectionResolver(settings.ssh)
        self.runner_registry = PersistentRunnerRegistry()
        self.adapters = DefaultDeviceAdapterFactory(
            use_mock=settings.use_mock_devices,
            resolver=self.ssh_resolver,
            runner_factory=self.runner_registry.get,
        )
        poll_monitoring = DefaultMonitoringProviderFactory(
            use_mock=settings.use_mock_devices,
            resolver=self.ssh_resolver,
            runner_factory=self.runner_registry.get,
        )
        self.monitoring = RuntimeStoreMonitoringFactory(self.runtime)

        # application services. The poll loop records live state; read use cases
        # read the latest snapshot (local SQLite, no separate cache needed).
        self.network = NetworkStateService(self.config, self.monitoring)
        self.poll_network = NetworkStateService(self.config, poll_monitoring)

        # use cases
        self.authenticate_user = AuthenticateUser(self.config, verify_password)
        self.get_dashboard_summary = GetDashboardSummary(
            self.config, self.network, self.runtime
        )
        self.list_devices = ListDevices(self.network)
        self.get_device_detail = GetDeviceDetail(self.network)
        self.list_clients = ListClients(self.network)
        self.get_topology = GetTopology(self.network, self.topology_provider)
        self.poll_device_state = PollDeviceState(
            self.poll_network, self.runtime, retention_days=settings.retention_days
        )
        self.read_baseline = ReadBaseline(
            self.config, self.adapters, self.applied_config, self.history
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

    def seed_desired_from_current(self) -> bool:
        """Populate ``desired_config.json`` from the baseline if it is absent.

        After the first baseline read the staged (desired) configuration should
        equal what is running, so the UI shows no spurious pending changes.
        Returns True if seeding occurred.
        """
        if self.desired_store.exists():
            return False
        if not self.current_store.exists():
            return False
        self.desired_store.save_all(self.current_store.load())
        return True

    def close(self) -> None:
        self.runtime.close()
        self.history.close()
        self.runner_registry.close_all()

