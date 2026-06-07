"""Tests for reverting pending changes to the last applied snapshot."""

from __future__ import annotations

import copy

from hsnc.config.applied_config_store import CurrentConfigStore
from hsnc.config.device_config_store import JsonDeviceConfigStore
from hsnc.config.layered_config_repository import (
    LayeredConfigRepository,
)
from hsnc.config.yaml_config_repository import YamlConfigRepository
from hsnc.entities import Vlan
from hsnc.use_cases.config_diff import GetConfigDiff
from hsnc.use_cases.revert_config import RevertPendingChanges

from .fakes import FakeAppliedConfigStore, FakeConfigWriter


def test_revert_noop_when_nothing_applied(config):
    writer = FakeConfigWriter(config)
    reverted = RevertPendingChanges(config, FakeAppliedConfigStore(), writer).execute()
    assert reverted == 0
    assert writer.saved == []


def test_revert_restores_applied_versions_and_clears_diff(config, devices):
    applied = FakeAppliedConfigStore(devices=copy.deepcopy(devices))
    writer = FakeConfigWriter(config)

    # make a pending edit to the desired config
    switch = config.get_device("switch-1")
    switch.vlans.append(Vlan(vlan_id=33, name="Lab", subnet="192.168.33.0/24"))
    assert GetConfigDiff(config, applied).execute().has_changes

    reverted = RevertPendingChanges(config, applied, writer).execute()
    assert reverted == 1
    # the writer (which updates the repo) restored the applied version
    assert GetConfigDiff(config, applied).execute().has_changes is False


def test_revert_skips_unchanged_devices(config, devices):
    applied = FakeAppliedConfigStore(devices=copy.deepcopy(devices))
    writer = FakeConfigWriter(config)
    # no pending edits -> nothing differs -> nothing written
    reverted = RevertPendingChanges(config, applied, writer).execute()
    assert reverted == 0
    assert writer.saved == []


def _real_repo(tmp_path):
    """Wire the real layered repo + current-config store with no baseline file."""
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "site.yaml").write_text("name: Test\n")
    (config_dir / "users.yaml").write_text("users: []\n")
    (config_dir / "devices.yaml").write_text(
        "devices:\n"
        "  - id: ap-1\n    name: AP 1\n    kind: access_point\n    site_id: s1\n"
        "  - id: switch-1\n    name: Switch 1\n    kind: switch\n    site_id: s1\n"
    )
    profiles = YamlConfigRepository(config_dir, backup_dir=tmp_path / "backups")
    desired = JsonDeviceConfigStore(tmp_path / "desired_config.json")
    current = JsonDeviceConfigStore(tmp_path / "current_config.json")
    config = LayeredConfigRepository(profiles, desired, current)
    applied = CurrentConfigStore(tmp_path, profiles, store=current)
    return config, applied, current


def test_revert_all_discards_edits_without_baseline(tmp_path):
    """Revert clears staged edits even when current_config.json was never written."""
    config, applied, current = _real_repo(tmp_path)
    assert not current.exists()

    ap = config.get_device("ap-1")
    ap.ssids.append("Test123")
    config.save_device(ap)
    sw = config.get_device("switch-1")
    sw.vlans.append(Vlan(vlan_id=456, name="Test", subnet=""))
    config.save_device(sw)

    diff = GetConfigDiff(config, applied)
    assert diff.execute().has_changes

    reverted = RevertPendingChanges(config, applied, config).execute()
    assert reverted == 2
    assert diff.execute().has_changes is False
    assert config.get_device("ap-1").ssids == []
    assert config.get_device("switch-1").vlans == []


def test_revert_single_device_without_baseline(tmp_path):
    """Per-device revert only touches the selected device when there is no baseline."""
    config, applied, _ = _real_repo(tmp_path)

    ap = config.get_device("ap-1")
    ap.ssids.append("Test123")
    config.save_device(ap)
    sw = config.get_device("switch-1")
    sw.vlans.append(Vlan(vlan_id=456, name="Test", subnet=""))
    config.save_device(sw)

    reverted = RevertPendingChanges(config, applied, config).execute(
        device_ids=["switch-1"]
    )
    assert reverted == 1
    # switch reverted, ap edit retained
    assert config.get_device("switch-1").vlans == []
    assert config.get_device("ap-1").ssids == ["Test123"]
