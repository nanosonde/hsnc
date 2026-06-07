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
from ..application.use_cases.baseline import ReadBaseline
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
from .broker.client import BrokerClient
from .broker.proxy_adapter import BrokerProxyAdapterFactory
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

#: Composition profiles. ``web`` wires the read-only/proxy stack used by the
#: Flask app (no device connections); ``broker`` wires the real device stack
#: used by the always-on Device Broker process.
PROFILE_WEB = "web"
PROFILE_BROKER = "broker"
#: The unified REST backend: real device adapters for configuration I/O, a live
#: poll loop that scrapes into the runtime store, and read endpoints that serve
#: the latest snapshot (no per-request device I/O).
PROFILE_API = "api"


@dataclass
class Settings:
    """Runtime configuration resolved from environment/defaults."""

    config_dir: Path
    data_dir: Path
    use_mock_devices: bool = True
    poll_interval_seconds: int = 30
    retention_days: int = 30
    baseline_on_start: bool = True
    broker_socket: Path = Path("/data/broker.sock")
    api_base_url: str = "http://127.0.0.1:8081"
    api_token: str = ""
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

    The ``profile`` selects how the device-facing ports are wired:

    * ``web`` — the Flask process. Device adapters proxy to the broker over the
      Unix socket and monitoring reads the latest snapshot from the runtime
      store, so **no request ever opens a device connection**.
    * ``broker`` — the Device Broker process. Real SSH adapters reuse persistent,
      pooled connections and monitoring scrapes the devices, writing the runtime
      store. The broker owns all device I/O.

    Inner layers (use cases, DTOs, templates) are identical across profiles;
    only the infrastructure bound to the ports differs.
    """

    def __init__(self, settings: Settings, profile: str = PROFILE_WEB) -> None:
        self.settings = settings
        self.profile = profile

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

        # connection-plane + monitoring-plane wiring differs per profile.
        self.runner_registry: PersistentRunnerRegistry | None = None
        self.ssh_resolver: SshConnectionResolver | None = None
        if profile in (PROFILE_BROKER, PROFILE_API):
            self.ssh_resolver = SshConnectionResolver(settings.ssh)
            self.runner_registry = PersistentRunnerRegistry()
            self.adapters = DefaultDeviceAdapterFactory(
                use_mock=settings.use_mock_devices,
                resolver=self.ssh_resolver,
                runner_factory=self.runner_registry.get,
            )
            live_monitoring = DefaultMonitoringProviderFactory(
                use_mock=settings.use_mock_devices,
                resolver=self.ssh_resolver,
                runner_factory=self.runner_registry.get,
            )
            poll_monitoring = live_monitoring
            if profile == PROFILE_API:
                # Read endpoints serve the latest runtime snapshot; the poll
                # loop keeps it fresh by scraping live monitoring.
                self.monitoring = RuntimeStoreMonitoringFactory(self.runtime)
            else:  # PROFILE_BROKER scrapes live on demand (it serves no reads)
                self.monitoring = live_monitoring
        else:  # PROFILE_WEB proxies device I/O to the broker; reads the snapshot
            self.adapters = BrokerProxyAdapterFactory(BrokerClient(settings.broker_socket))
            self.monitoring = RuntimeStoreMonitoringFactory(self.runtime)
            poll_monitoring = self.monitoring

        # application services. The poll loop records live state; read use cases
        # read the latest snapshot (local SQLite, no separate cache needed).
        self.network = NetworkStateService(self.config, self.monitoring)
        self.network_cached = self.network
        self.poll_network = NetworkStateService(self.config, poll_monitoring)

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
        if self.runner_registry is not None:
            self.runner_registry.close_all()

