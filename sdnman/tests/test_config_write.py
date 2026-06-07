"""Tests for editing config and writing it back to the desired-config store."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from sdnman.application.use_cases.edit_device_config import (
    ConfigEditError,
    DeleteVlan,
    SavePort,
    SaveSsids,
    SaveVlan,
)
from sdnman.infrastructure.config.device_config_store import JsonDeviceConfigStore
from sdnman.infrastructure.config.layered_config_repository import (
    LayeredConfigRepository,
)
from sdnman.infrastructure.config.yaml_config_repository import (
    YamlConfigRepository,
)

_PROJECT_CONFIG = Path(__file__).resolve().parents[2] / "config"


@pytest.fixture
def repo(tmp_path) -> LayeredConfigRepository:
    config_dir = tmp_path / "config"
    shutil.copytree(_PROJECT_CONFIG, config_dir)
    # Tests run against the committed sample inventory, not any local trial
    # devices.yaml (which is git-ignored and may be absent or minimal).
    shutil.copyfile(
        _PROJECT_CONFIG / "devices.yaml.example", config_dir / "devices.yaml"
    )
    backup_dir = tmp_path / "config-backups"
    profiles = YamlConfigRepository(config_dir, backup_dir=backup_dir)
    desired_path = tmp_path / "desired_config.json"
    shutil.copyfile(
        _PROJECT_CONFIG / "desired_config.json.example", desired_path
    )
    desired = JsonDeviceConfigStore(desired_path)
    return LayeredConfigRepository(profiles, desired)


def test_save_vlan_persisted(repo):
    SaveVlan(repo, repo).execute("switch-1", vlan_id=99, name="Guest", subnet="")

    reloaded = repo.get_device("switch-1")
    assert any(v.vlan_id == 99 and v.name == "Guest" for v in reloaded.vlans)


def test_save_vlan_rejects_invalid_id(repo):
    with pytest.raises(ConfigEditError):
        SaveVlan(repo, repo).execute("switch-1", vlan_id=5000, name="Bad")


def test_save_vlan_accepts_valid_cidr_subnet(repo):
    SaveVlan(repo, repo).execute(
        "switch-1", vlan_id=42, name="Lab", subnet="192.168.42.0/24"
    )
    reloaded = repo.get_device("switch-1")
    assert any(
        v.vlan_id == 42 and v.subnet == "192.168.42.0/24" for v in reloaded.vlans
    )


@pytest.mark.parametrize(
    "subnet",
    ["192.168.1.0", "192.168.1.0/33", "10.0.0.0/-1", "not-a-subnet", "300.1.1.0/24"],
)
def test_save_vlan_rejects_invalid_subnet(repo, subnet):
    with pytest.raises(ConfigEditError):
        SaveVlan(repo, repo).execute("switch-1", vlan_id=43, name="Bad", subnet=subnet)


def test_delete_vlan_blocked_when_used_as_pvid(repo):
    switch = repo.get_device("switch-1")
    pvid = switch.ports[0].pvid
    with pytest.raises(ConfigEditError):
        DeleteVlan(repo, repo).execute("switch-1", pvid)


def test_save_port_validates_pvid_against_defined_vlans(repo):
    with pytest.raises(ConfigEditError):
        SavePort(repo, repo).execute(
            "switch-1",
            number=1,
            name="p1",
            enabled=True,
            mode="access",
            pvid=4000,
            tagged_vlans=[],
        )


def test_save_port_roundtrip(repo):
    SavePort(repo, repo).execute(
        "switch-1",
        number=1,
        name="uplink",
        enabled=True,
        mode="trunk",
        pvid=1,
        tagged_vlans=[10, 20],
    )
    reloaded = repo.get_device("switch-1")
    port = next(p for p in reloaded.ports if p.number == 1)
    assert port.name == "uplink"
    assert port.mode.value == "trunk"
    assert port.tagged_vlans == [10, 20]


def test_save_ssids_roundtrip(repo):
    SaveSsids(repo, repo).execute("ap-1", ["Corp", "Guest"])
    reloaded = repo.get_device("ap-1")
    assert reloaded.ssids == ["Corp", "Guest"]


def test_backup_roundtrip_preserves_layered_config(tmp_path):
    """The layered archive must carry desired_config.json and current_config.json."""
    config_dir = tmp_path / "config"
    shutil.copytree(_PROJECT_CONFIG, config_dir)
    shutil.copyfile(
        _PROJECT_CONFIG / "devices.yaml.example", config_dir / "devices.yaml"
    )
    profiles = YamlConfigRepository(config_dir, backup_dir=tmp_path / "backups")
    desired_path = tmp_path / "desired_config.json"
    current_path = tmp_path / "current_config.json"
    shutil.copyfile(_PROJECT_CONFIG / "desired_config.json.example", desired_path)
    shutil.copyfile(_PROJECT_CONFIG / "desired_config.json.example", current_path)
    desired = JsonDeviceConfigStore(desired_path)
    current = JsonDeviceConfigStore(current_path)
    repo = LayeredConfigRepository(profiles, desired, current)

    # stage an edit so desired diverges from the seed
    SaveVlan(repo, repo).execute("switch-1", vlan_id=77, name="Backup", subnet="")
    files = repo.export_files()
    assert "desired_config.json" in files
    assert "current_config.json" in files

    # wipe both JSON stores, then restore from the archive
    desired_path.write_text("{}")
    current_path.write_text("{}")
    repo.import_files(files)

    reloaded = repo.get_device("switch-1")
    assert any(v.vlan_id == 77 and v.name == "Backup" for v in reloaded.vlans)
