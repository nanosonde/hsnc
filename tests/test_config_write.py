"""Tests for editing config and writing it back to YAML (with backups)."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from omui_clone.application.use_cases.edit_device_config import (
    ConfigEditError,
    DeleteVlan,
    SavePort,
    SaveSsids,
    SaveVlan,
)
from omui_clone.infrastructure.config.yaml_config_repository import (
    YamlConfigRepository,
)

_PROJECT_CONFIG = Path(__file__).resolve().parents[1] / "config"


@pytest.fixture
def repo(tmp_path) -> YamlConfigRepository:
    config_dir = tmp_path / "config"
    shutil.copytree(_PROJECT_CONFIG, config_dir)
    backup_dir = tmp_path / "config-backups"
    return YamlConfigRepository(config_dir, backup_dir=backup_dir)


def _devices_yaml(repo: YamlConfigRepository) -> dict:
    path = repo.config_dir / "devices.yaml"
    return yaml.safe_load(path.read_text())


def test_save_vlan_writes_yaml_and_backs_up(repo, tmp_path):
    SaveVlan(repo, repo).execute("switch-1", vlan_id=99, name="Guest", subnet="")

    data = _devices_yaml(repo)
    switch = next(d for d in data["devices"] if d["id"] == "switch-1")
    assert any(v["vlan_id"] == 99 and v["name"] == "Guest" for v in switch["vlans"])

    backups = list((tmp_path / "config-backups").glob("*/devices.yaml"))
    assert backups, "expected a timestamped backup of devices.yaml"


def test_save_vlan_rejects_invalid_id(repo):
    with pytest.raises(ConfigEditError):
        SaveVlan(repo, repo).execute("switch-1", vlan_id=5000, name="Bad")


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
