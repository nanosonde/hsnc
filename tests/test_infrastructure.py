"""Tests for infrastructure adapters: YAML config, SQLite store, backup, factory."""

from __future__ import annotations

from datetime import UTC

import pytest

from omada_clone.application.use_cases.backup import ExportBackup, ImportBackup
from omada_clone.domain.entities import (
    AssociationFailure,
    Client,
    Device,
)
from omada_clone.domain.enums import ConnectionType, DeviceKind, DeviceStatus
from omada_clone.domain.value_objects import IpAddress, MacAddress
from omada_clone.infrastructure.config.yaml_config_repository import (
    YamlConfigRepository,
)
from omada_clone.infrastructure.devices.factory import DefaultDeviceAdapterFactory
from omada_clone.infrastructure.persistence.sqlite_runtime_store import (
    SqliteRuntimeStore,
)

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
    "    mac: B0:4E:26:00:00:10\n"
    "    ip: 192.168.50.2\n"
    "    vlans:\n"
    "      - vlan_id: 10\n"
    "        name: Mgmt\n"
    "    ports:\n"
    "      - number: 1\n"
    "        mode: trunk\n"
    "        pvid: 1\n"
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
    assert device.vlans[0].vlan_id == 10
    assert device.ports[0].mode.value == "trunk"


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


def test_backup_roundtrip(config_dir, tmp_path):
    repo = YamlConfigRepository(config_dir)
    store = SqliteRuntimeStore(tmp_path / "rt.db")
    from datetime import datetime
    now = datetime(2026, 1, 1, tzinfo=UTC)
    store.record_association_failures([AssociationFailure("A", 2)], now)

    archive = ExportBackup(repo, store).execute()

    # wipe runtime + config
    store.import_rows({})
    (config_dir / "site.yaml").write_text("id: default\nname: WIPED\n")

    ImportBackup(repo, store).execute(archive)
    assert repo.get_site().name == "My Site"
    assert store.latest_association_failures() == [AssociationFailure("A", 2)]
    store.close()


def test_real_adapter_factory_raises_not_implemented():
    factory = DefaultDeviceAdapterFactory(use_mock=False)
    device = Device(
        id="switch-1", name="SW", kind=DeviceKind.SWITCH,
        mac=MacAddress("B0:4E:26:00:00:10"),
    )
    adapter = factory.for_device(device)
    with pytest.raises(NotImplementedError):
        adapter.fetch_status(device)


def test_mock_adapter_factory_returns_data():
    factory = DefaultDeviceAdapterFactory(use_mock=True)
    device = Device(
        id="switch-1", name="SW", kind=DeviceKind.SWITCH,
        mac=MacAddress("B0:4E:26:00:00:10"),
    )
    adapter = factory.for_device(device)
    assert len(adapter.fetch_clients(device)) == 6
