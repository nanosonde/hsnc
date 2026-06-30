"""Tests for the JetStream CLI adapter, driven by a FakeSshRunner."""

from __future__ import annotations

import pytest

from hsnc.devices.jetstream.adapter import JetStreamCliAdapter
from hsnc.devices.ssh_transport import (
    FakeSshRunner,
    SshConnectionResolver,
    SshConnectionSettings,
    SshError,
)
from hsnc.entities import Device, SwitchPort, Vlan
from hsnc.enums import DeviceKind, PortMode
from hsnc.value_objects import IpAddress, MacAddress

_RUNNING_CONFIG = (
    "#\n"
    "hostname core-switch\n"
    "#\n"
    "vlan 1\n"
    " name System-VLAN\n"
    "vlan 10\n"
    " name Management\n"
    "#\n"
    "interface gigabitEthernet 1/0/1\n"
    " switchport mode access\n"
    " switchport access vlan 10\n"
    " switchport pvid 10\n"
    "#\n"
    "interface gigabitEthernet 1/0/2\n"
    " switchport mode trunk\n"
    " switchport general allowed vlan 1,10\n"
    " switchport pvid 1\n"
    " shutdown\n"
    "#\n"
    "end\n"
)

# Real capture from a TP-Link SG2005P-PD: quoted names, an `interface vlan` SVI,
# `switchport general allowed vlan ... untagged|tagged`, and the shell echoes /
# privileged prompt that surround the config in an interactive session.
_REAL_RUNNING_CONFIG = (
    "enable\n"
    "SG2005P-PD-1#show running-config\n"
    "!SG2005P-PD\n"
    "#\n"
    "vlan 1\n"
    ' name "System-VLAN"\n'
    "#\n"
    "vlan 20\n"
    ' name "FB_LAN_Guest"\n'
    "#\n"
    "vlan 40\n"
    ' name "FREIFUNK_CLIENT"\n'
    "#\n"
    'hostname "SG2005P-PD-1"\n'
    'location "Hauptverteilung"\n'
    "#\n"
    "interface vlan 1\n"
    "  ip address 10.10.10.6 255.255.255.0\n"
    "#\n"
    "interface gigabitEthernet 1/0/3\n"
    '  description "Buderus KNX10"\n'
    "  switchport general allowed vlan 20 untagged\n"
    "  switchport pvid 20\n"
    "  no spanning-tree\n"
    "#\n"
    "interface gigabitEthernet 1/0/5\n"
    '  description "TRUNK"\n'
    "  switchport general allowed vlan 5,20,30,40 tagged\n"
    "#\n"
    "end\n"
    "SG2005P-PD-1#\n"
)


def _device() -> Device:
    return Device(
        id="switch-1",
        name="TL-SG2210P",
        kind=DeviceKind.SWITCH,
        mac=MacAddress("B0:4E:26:00:00:10"),
        model="TP-Link JetStream TL-SG2210P",
        ip=IpAddress("192.168.50.2"),
    )


def _adapter(runner: FakeSshRunner) -> JetStreamCliAdapter:
    resolver = SshConnectionResolver(SshConnectionSettings())
    return JetStreamCliAdapter(resolver=resolver, runner_factory=lambda target: runner)


def test_fetch_config_parses_vlans_and_ports() -> None:
    runner = FakeSshRunner(shell_output=_RUNNING_CONFIG)
    device = _adapter(runner).fetch_config(_device())

    assert runner.shell_invocations == [["enable", "show running-config"]]
    assert device.name == "core-switch"
    assert {v.vlan_id: v.name for v in device.vlans} == {1: "System-VLAN", 10: "Management"}

    ports = {p.number: p for p in device.ports}
    assert ports[1].mode is PortMode.ACCESS
    assert ports[1].pvid == 10
    assert ports[2].mode is PortMode.TRUNK
    assert ports[2].tagged_vlans == [1, 10]
    assert ports[2].enabled is False


def test_fetch_config_parses_real_sg2005p_running_config() -> None:
    runner = FakeSshRunner(shell_output=_REAL_RUNNING_CONFIG)
    device = _adapter(runner).fetch_config(_device())

    # Quoted hostname/VLAN names are unquoted.
    assert device.name == "SG2005P-PD-1"
    assert {v.vlan_id: v.name for v in device.vlans} == {
        1: "System-VLAN",
        20: "FB_LAN_Guest",
        40: "FREIFUNK_CLIENT",
    }

    ports = {p.number: p for p in device.ports}
    # `interface vlan 1` (the management SVI) must not become a physical port.
    assert set(ports) == {3, 5}
    # Untagged member -> access with that PVID.
    assert ports[3].mode is PortMode.ACCESS
    assert ports[3].pvid == 20
    assert ports[3].tagged_vlans == []
    # Tagged members -> trunk.
    assert ports[5].mode is PortMode.TRUNK
    assert ports[5].tagged_vlans == [5, 20, 30, 40]


def test_fetch_config_is_authoritative_and_clears_stale_entries() -> None:
    # An empty running-config means the switch has no VLANs/ports configured.
    # A re-read is the single source of truth, so stale inventory entries must
    # be cleared rather than preserved.
    runner = FakeSshRunner(shell_output="#\nend\n")
    device = _device()
    device.vlans = [Vlan(10, "Stale")]
    device.ports = [SwitchPort(number=1, name="Stale")]

    fresh = _adapter(runner).fetch_config(device)

    assert fresh.vlans == []
    assert fresh.ports == []


def test_push_config_runs_single_interactive_shell_session() -> None:
    runner = FakeSshRunner()
    device = _device()
    device.vlans = [Vlan(1, "Default"), Vlan(10, "Management")]
    device.ports = [SwitchPort(number=1, mode=PortMode.ACCESS, pvid=10)]
    _adapter(runner).push_config(device)

    # A clean push is three phases: snapshot, body (no save), then persist.
    assert len(runner.shell_invocations) == 3
    snapshot, body, save = runner.shell_invocations
    assert snapshot == ["enable", "show running-config"]
    assert body[0] == "configure"
    assert "hostname TL-SG2210P" in body
    assert "copy running-config startup-config" not in body
    assert save == ["enable", "copy running-config startup-config"]


def test_push_config_persists_only_after_a_clean_apply() -> None:
    runner = FakeSshRunner(shell_outputs=["#\nend\n", "", ""])
    device = _device()
    device.vlans = [Vlan(10, "Management")]
    _adapter(runner).push_config(device)

    # The final invocation is the deferred save.
    assert runner.shell_invocations[-1] == ["enable", "copy running-config startup-config"]


def test_push_config_rolls_back_running_config_on_cli_rejection() -> None:
    # Snapshot read returns a prior config; the body push is rejected by the
    # switch; the save must never run and the snapshot must be re-pushed.
    runner = FakeSshRunner(
        shell_outputs=[
            _RUNNING_CONFIG,  # snapshot
            "% Unrecognized command: switchport bogus",  # body push rejected
            "",  # restore push
        ]
    )
    device = _device()
    device.vlans = [Vlan(99, "New")]

    with pytest.raises(SshError, match="rejected"):
        _adapter(runner).push_config(device)

    sent = [cmd for batch in runner.shell_invocations for cmd in batch]
    # startup-config was never written.
    assert "copy running-config startup-config" not in sent
    # The captured prior config (hostname core-switch) was re-pushed to restore.
    restore = runner.shell_invocations[-1]
    assert restore[0] == "configure"
    assert "hostname core-switch" in restore


def test_push_config_attempts_restore_on_transport_drop() -> None:
    # A command failing mid-push (transport drop) raises; the save must not run.
    runner = FakeSshRunner(
        shell_outputs=[_RUNNING_CONFIG],
        errors=["configure"],
    )
    device = _device()
    device.vlans = [Vlan(99, "New")]

    with pytest.raises(SshError):
        _adapter(runner).push_config(device)

    sent = [cmd for batch in runner.shell_invocations for cmd in batch]
    assert "copy running-config startup-config" not in sent

