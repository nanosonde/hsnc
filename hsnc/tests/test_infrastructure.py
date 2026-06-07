"""Tests for infrastructure adapters: YAML config, SQLite store, backup, factory."""

from __future__ import annotations

from datetime import UTC

import pytest

from hsnc.config.yaml_config_repository import (
    YamlConfigRepository,
)
from hsnc.devices.factory import DefaultDeviceAdapterFactory
from hsnc.devices.jetstream_cli_adapter import JetStreamCliAdapter
from hsnc.devices.openwrt_ssh_adapter import OpenWrtSshAdapter
from hsnc.entities import (
    AssociationFailure,
    Client,
    Device,
)
from hsnc.enums import ConnectionType, DeviceKind, DeviceStatus
from hsnc.persistence.sqlite_runtime_store import (
    SqliteRuntimeStore,
)
from hsnc.use_cases.backup import ExportBackup, ImportBackup
from hsnc.value_objects import IpAddress, MacAddress

SITE_YAML = "id: default\nname: My Site\ncountry: DE\n"
USERS_YAML = (
    "users:\n"
    "  - username: admin\n"
    "    password_hash: x\n"
    "    role: admin\n"
)
DEVICES_YAML = (
    "devices:\n"
    "  - id: switch-1\n"
    "    name: SW\n"
    "    kind: switch\n"
    "    ip: 192.168.50.2\n"
    "    connection:\n"
    "      username: admin\n"
    "      port: 22\n"
    "    monitoring:\n"
    "      type: ssh\n"
)


@pytest.fixture
def config_dir(tmp_path):
    (tmp_path / "site.yaml").write_text(SITE_YAML)
    (tmp_path / "users.yaml").write_text(USERS_YAML)
    (tmp_path / "devices.yaml").write_text(DEVICES_YAML)
    return tmp_path


def test_yaml_config_repository_reads(config_dir):
    repo = YamlConfigRepository(config_dir)
    assert repo.get_site().name == "My Site"
    assert len(repo.list_users()) == 1
    device = repo.get_device("switch-1")
    assert device is not None
    assert device.kind is DeviceKind.SWITCH
    assert device.ip == IpAddress("192.168.50.2")
    assert device.connection is not None
    assert device.connection.username == "admin"
    assert device.monitoring is not None
    assert device.monitoring.type == "ssh"


def test_yaml_config_archive_roundtrip(config_dir):
    repo = YamlConfigRepository(config_dir)
    files = repo.export_files()
    assert "site.yaml" in files
    # mutate then re-import
    repo.import_files(files)
    assert repo.get_site().name == "My Site"


def test_sqlite_runtime_store(tmp_path):
    store = SqliteRuntimeStore(tmp_path / "rt.db")
    device = Device(
        id="d1", name="D1", kind=DeviceKind.SWITCH,
        mac=MacAddress("B0:4E:26:00:00:10"), status=DeviceStatus.CONNECTED,
    )
    client = Client(
        id="c1", name="C1", mac=MacAddress("AC:1F:6B:00:00:01"),
        connection=ConnectionType.WIRED, status=DeviceStatus.CONNECTED,
        ip=IpAddress("192.168.50.10"),
    )
    from datetime import datetime
    now = datetime(2026, 1, 1, tzinfo=UTC)
    store.record_device_status(device, now)
    store.record_client_session(client, now)
    store.record_association_failures([AssociationFailure("Timeout", 3)], now)

    failures = store.latest_association_failures()
    assert failures == [AssociationFailure("Timeout", 3)]

    rows = store.export_rows()
    assert len(rows["device_status"]) == 1
    assert len(rows["client_session"]) == 1
    store.close()


def test_sqlite_import_rows_replaces(tmp_path):
    store = SqliteRuntimeStore(tmp_path / "rt.db")
    from datetime import datetime
    now = datetime(2026, 1, 1, tzinfo=UTC)
    store.record_association_failures([AssociationFailure("A", 1)], now)
    exported = store.export_rows()
    store.import_rows({})  # wipe
    assert store.latest_association_failures() == []
    store.import_rows(exported)  # restore
    assert store.latest_association_failures() == [AssociationFailure("A", 1)]
    store.close()


def test_jsonl_apply_history_store_roundtrips(tmp_path):
    from datetime import datetime

    from hsnc.entities import ApplyEvent, ApplyOutcome
    from hsnc.persistence.jsonl_apply_history_store import (
        JsonlApplyHistoryStore,
    )

    store = JsonlApplyHistoryStore(tmp_path / "history.jsonl")
    store.record_apply_event(
        ApplyEvent(
            applied_at=datetime(2026, 6, 1, 12, 0, tzinfo=UTC),
            username="admin",
            ok=False,
            outcomes=[
                ApplyOutcome("d1", "Switch", ok=True),
                ApplyOutcome("d2", "Gateway", ok=False, message="not implemented"),
            ],
        )
    )
    store.record_apply_event(
        ApplyEvent(
            applied_at=datetime(2026, 6, 2, 9, 0, tzinfo=UTC),
            username="admin",
            ok=True,
            action="reread",
            outcomes=[ApplyOutcome("d1", "Switch", ok=True)],
        )
    )

    listed = store.list_apply_events()
    assert len(listed) == 2
    # newest first
    assert listed[0].action == "reread"
    assert listed[1].username == "admin"
    assert listed[1].ok is False
    assert listed[1].outcomes[1].message == "not implemented"

    # export/import round-trips the raw file contents
    exported = store.export_text()
    store.import_text("")
    assert store.list_apply_events() == []
    store.import_text(exported)
    restored = store.list_apply_events()
    assert len(restored) == 2
    assert restored[0].action == "reread"
    store.close()


def test_sqlite_prune_removes_old_rows(tmp_path):
    from datetime import datetime

    store = SqliteRuntimeStore(tmp_path / "rt.db")
    old = datetime(2026, 1, 1, tzinfo=UTC)
    new = datetime(2026, 6, 1, tzinfo=UTC)
    device = Device(
        id="d1", name="D1", kind=DeviceKind.SWITCH,
        mac=MacAddress("B0:4E:26:00:00:10"), status=DeviceStatus.CONNECTED,
    )
    store.record_device_status(device, old)
    store.record_device_status(device, new)
    store.record_association_failures([AssociationFailure("A", 1)], old)

    removed = store.prune(datetime(2026, 3, 1, tzinfo=UTC))
    assert removed == 2  # old device_status + old association_failure
    rows = store.export_rows()
    assert len(rows["device_status"]) == 1
    store.close()


def test_backup_roundtrip(config_dir, tmp_path):
    from datetime import datetime

    from hsnc.entities import ApplyEvent, ApplyOutcome
    from hsnc.persistence.jsonl_apply_history_store import (
        JsonlApplyHistoryStore,
    )

    repo = YamlConfigRepository(config_dir)
    store = SqliteRuntimeStore(tmp_path / "rt.db")
    history = JsonlApplyHistoryStore(tmp_path / "history.jsonl")
    now = datetime(2026, 1, 1, tzinfo=UTC)
    store.record_association_failures([AssociationFailure("A", 2)], now)
    history.record_apply_event(
        ApplyEvent(
            applied_at=now,
            username="admin",
            ok=True,
            outcomes=[ApplyOutcome("d1", "Switch", ok=True)],
        )
    )

    archive = ExportBackup(repo, store, history).execute()

    # wipe runtime + history + config
    store.import_rows({})
    history.import_text("")
    (config_dir / "site.yaml").write_text("id: default\nname: WIPED\n")

    ImportBackup(repo, store, history).execute(archive)
    assert repo.get_site().name == "My Site"
    assert store.latest_association_failures() == [AssociationFailure("A", 2)]
    assert len(history.list_apply_events()) == 1
    store.close()
    history.close()


def test_real_adapter_factory_routes_by_kind():
    factory = DefaultDeviceAdapterFactory(use_mock=False)
    switch = Device(
        id="switch-1", name="SW", kind=DeviceKind.SWITCH,
        mac=MacAddress("B0:4E:26:00:00:10"),
    )
    gateway = Device(
        id="gateway-1", name="GW", kind=DeviceKind.GATEWAY,
        mac=MacAddress("AC:1F:6B:A0:00:01"),
    )
    assert isinstance(factory.for_device(switch), JetStreamCliAdapter)
    assert isinstance(factory.for_device(gateway), OpenWrtSshAdapter)


def test_mock_monitoring_factory_returns_data():
    from hsnc.devices.monitoring import (
        DefaultMonitoringProviderFactory,
    )

    factory = DefaultMonitoringProviderFactory(use_mock=True)
    device = Device(
        id="switch-1", name="SW", kind=DeviceKind.SWITCH,
        mac=MacAddress("B0:4E:26:00:00:10"),
    )
    provider = factory.for_device(device)
    assert len(provider.fetch_clients(device)) == 6
