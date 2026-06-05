"""Tests for the JetStream CLI adapter, driven by a FakeSshRunner."""

from __future__ import annotations

from sdnman.domain.entities import Device, SwitchPort, Vlan
from sdnman.domain.enums import ConnectionType, DeviceKind, DeviceStatus, PortMode
from sdnman.domain.value_objects import IpAddress, MacAddress
from sdnman.infrastructure.devices.jetstream_cli_adapter import JetStreamCliAdapter
from sdnman.infrastructure.devices.monitoring import JetStreamSshMonitoringProvider
from sdnman.infrastructure.devices.ssh_transport import (
    FakeSshRunner,
    SshConnectionResolver,
    SshConnectionSettings,
)

_SYSTEM_INFO = (
    "Device Description - JetStream Gigabit Smart Switch (mock)\n"
    "Device Name        - TL-SG2210P\n"
    "Device Model       - TL-SG2210P\n"
    "Software Version   - 5.0.6 Build 20231010 (mock)\n"
    "MAC Address        - 00-11-22-33-44-02\n"
    "Running Time       - 3 days 04:21:09\n"
)

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

_MAC_TABLE = (
    "MAC Address        VLAN   Port      Type\n"
    "-----------------  -----  --------  -------\n"
    "00-11-22-aa-bb-01  10     Gi1/0/1   dynamic\n"
    "00-11-22-aa-bb-03  20     Gi1/0/3   dynamic\n"
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


def _monitor(runner: FakeSshRunner) -> JetStreamSshMonitoringProvider:
    resolver = SshConnectionResolver(SshConnectionSettings())
    return JetStreamSshMonitoringProvider(
        resolver=resolver, runner_factory=lambda target: runner
    )


def test_fetch_status_parses_system_info() -> None:
    runner = FakeSshRunner(shell_output=_SYSTEM_INFO)
    device = _monitor(runner).fetch_status(_device())

    assert runner.shell_invocations == [["show system-info"]]
    assert device.status is DeviceStatus.CONNECTED
    assert device.model == "TL-SG2210P"
    assert device.firmware == "5.0.6 Build 20231010 (mock)"
    assert str(device.mac) == "00:11:22:33:44:02"
    assert device.uptime_seconds == 3 * 86400 + 4 * 3600 + 21 * 60 + 9


def test_fetch_config_parses_vlans_and_ports() -> None:
    runner = FakeSshRunner({"show running-config": _RUNNING_CONFIG})
    device = _adapter(runner).fetch_config(_device())

    assert device.name == "core-switch"
    assert {v.vlan_id: v.name for v in device.vlans} == {1: "System-VLAN", 10: "Management"}

    ports = {p.number: p for p in device.ports}
    assert ports[1].mode is PortMode.ACCESS
    assert ports[1].pvid == 10
    assert ports[2].mode is PortMode.TRUNK
    assert ports[2].tagged_vlans == [1, 10]
    assert ports[2].enabled is False


def test_fetch_clients_from_mac_table() -> None:
    runner = FakeSshRunner(shell_output=_MAC_TABLE)
    clients = _monitor(runner).fetch_clients(_device())

    assert runner.shell_invocations == [["show mac address-table"]]
    assert [str(c.mac) for c in clients] == ["00:11:22:AA:BB:01", "00:11:22:AA:BB:03"]
    assert clients[0].connection is ConnectionType.WIRED
    assert clients[0].ap_or_port == "Gi1/0/1"


def test_fetch_config_is_authoritative_and_clears_stale_entries() -> None:
    # An empty running-config means the switch has no VLANs/ports configured.
    # A re-read is the single source of truth, so stale inventory entries must
    # be cleared rather than preserved.
    runner = FakeSshRunner({"show running-config": "#\nend\n"})
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

    assert len(runner.shell_invocations) == 1
    lines = runner.shell_invocations[0]
    assert lines[0] == "configure"
    assert "hostname TL-SG2210P" in lines
    assert lines[-1] == "copy running-config startup-config"
