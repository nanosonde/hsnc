"""Tests for the OpenWrt SSH adapter, driven by a FakeSshRunner."""

from __future__ import annotations

from hsnc.devices.openwrt.adapter import OpenWrtSshAdapter
from hsnc.devices.ssh_transport import (
    FakeSshRunner,
    SshConnectionResolver,
    SshConnectionSettings,
)
from hsnc.entities import Device
from hsnc.enums import DeviceKind, PortMode
from hsnc.value_objects import IpAddress, MacAddress

_UCI_SYSTEM = "system.@system[0]=system\nsystem.@system[0].hostname='gw-edge'\n"
_UCI_NETWORK = (
    "network.lan=interface\n"
    "network.lan.ipaddr='192.168.50.254'\n"
    "network.@bridge-vlan[0]=bridge-vlan\n"
    "network.@bridge-vlan[0].vlan='1'\n"
    "network.@bridge-vlan[0].ports='lan1:u* lan2:u*'\n"
    "network.@bridge-vlan[1]=bridge-vlan\n"
    "network.@bridge-vlan[1].vlan='10'\n"
    "network.@bridge-vlan[1].ports='lan3:t lan4:t'\n"
)
_UCI_WIRELESS = (
    "wireless.@wifi-iface[0]=wifi-iface\n"
    "wireless.@wifi-iface[0].ssid='HomeNet'\n"
    "wireless.@wifi-iface[1]=wifi-iface\n"
    "wireless.@wifi-iface[1].ssid='HomeNet-Guest'\n"
)


def _device() -> Device:
    return Device(
        id="gateway-1",
        name="ER605",
        kind=DeviceKind.GATEWAY,
        mac=MacAddress("AC:1F:6B:A0:00:01"),
        model="TP-Link ER605 (OpenWrt)",
        ip=IpAddress("192.168.50.254"),
    )


def _adapter(runner: FakeSshRunner) -> OpenWrtSshAdapter:
    resolver = SshConnectionResolver(SshConnectionSettings())
    return OpenWrtSshAdapter(resolver=resolver, runner_factory=lambda target: runner)


def test_fetch_config_parses_vlans_ports_and_ssids() -> None:
    runner = FakeSshRunner(
        {
            "uci show system": _UCI_SYSTEM,
            "uci show network": _UCI_NETWORK,
            "uci show wireless": _UCI_WIRELESS,
        }
    )
    device = _adapter(runner).fetch_config(_device())

    assert device.name == "gw-edge"
    assert str(device.ip) == "192.168.50.254"
    assert [v.vlan_id for v in device.vlans] == [1, 10]
    assert device.ssids == ["HomeNet", "HomeNet-Guest"]

    ports = {p.number: p for p in device.ports}
    assert ports[1].pvid == 1
    assert ports[1].mode is PortMode.ACCESS
    assert ports[3].mode is PortMode.TRUNK
    assert ports[3].tagged_vlans == [10]


def test_fetch_config_is_authoritative_and_clears_stale_entries() -> None:
    # The device reports no bridge-vlans, no wireless and no ports, but the
    # inventory still carries stale values. A re-read is the single source of
    # truth, so the returned device must come back empty, not keep the old data.
    from hsnc.entities import SwitchPort, Vlan

    runner = FakeSshRunner({"uci show system": _UCI_SYSTEM})  # network/wireless empty
    device = _device()
    device.vlans = [Vlan(vlan_id=10, name="Stale")]
    device.ports = [SwitchPort(number=1, name="Stale")]
    device.ssids = ["StaleNet"]

    fresh = _adapter(runner).fetch_config(device)

    assert fresh.vlans == []
    assert fresh.ports == []
    assert fresh.ssids == []


def test_push_config_clears_existing_bridge_vlans_then_renders() -> None:
    runner = FakeSshRunner({"uci show network": _UCI_NETWORK})
    device = _device()
    device.vlans = []  # gateway has no declarative vlans -> only deletes + base sets
    _adapter(runner).push_config(device)

    deletes = [c for c in runner.commands if c == "uci delete network.@bridge-vlan[0]"]
    assert len(deletes) == 2  # two existing bridge-vlan sections cleared
    assert "uci commit" in runner.commands
    assert any(c.startswith("uci set system.@system[0].hostname=") for c in runner.commands)


def test_push_config_reverts_staging_on_failure() -> None:
    import pytest

    from hsnc.devices.ssh_transport import SshError

    # Fail while staging the IP address: nothing should be committed, and the
    # staged batch must be reverted so the running config stays untouched.
    runner = FakeSshRunner(
        {"uci show network": _UCI_NETWORK},
        errors=["uci set network.lan.ipaddr"],
    )
    device = _device()
    device.vlans = []

    with pytest.raises(SshError):
        _adapter(runner).push_config(device)

    assert "uci commit" not in runner.commands
    # A leading revert clears stale staging and a trailing revert rolls back the
    # partial batch -> the failing push issues `uci revert` at least twice.
    assert runner.commands.count("uci revert") >= 2

