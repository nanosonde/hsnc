"""Tests for reverting pending changes to the last applied snapshot."""

from __future__ import annotations

import copy

from sdnman.application.use_cases.config_diff import GetConfigDiff
from sdnman.application.use_cases.revert_config import RevertPendingChanges
from sdnman.domain.entities import Vlan

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
