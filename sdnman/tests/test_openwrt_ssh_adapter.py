"""Tests for the OpenWrt SSH adapter, driven by a FakeSshRunner."""

from __future__ import annotations

import json

from sdnman.domain.entities import Device
from sdnman.domain.enums import ConnectionType, DeviceKind, DeviceStatus, PortMode
from sdnman.domain.value_objects import IpAddress, MacAddress
from sdnman.infrastructure.devices.monitoring import OpenWrtSshMonitoringProvider
from sdnman.infrastructure.devices.openwrt_ssh_adapter import OpenWrtSshAdapter
from sdnman.infrastructure.devices.ssh_transport import (
    FakeSshRunner,
    SshConnectionResolver,
    SshConnectionSettings,
)

_BOARD = json.dumps(
    {
        "hostname": "gateway-1",
        "model": "TP-Link ER605 (mock)",
        "release": {"distribution": "OpenWrt", "version": "23.05.3"},
    }
)
_LAN_STATUS = json.dumps({"up": True, "uptime": 4242, "ipv4-address": []})

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
_LEASES = json.dumps(
    {
        "device": {
            "br-lan": {
                "ipv4-leases": [
                    {"mac": "1c:61:b4:00:11:22", "address": "192.168.50.20", "hostname": "desktop"},
                    {"mac": "a4:83:e7:00:33:44", "address": "192.168.50.21", "hostname": ""},
                ]
            }
        }
    }
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


def _monitor(runner: FakeSshRunner) -> OpenWrtSshMonitoringProvider:
    resolver = SshConnectionResolver(SshConnectionSettings())
    return OpenWrtSshMonitoringProvider(
        resolver=resolver, runner_factory=lambda target: runner
    )


def test_fetch_status_parses_board_and_uptime() -> None:
    runner = FakeSshRunner(
        {
            "ubus call system board": _BOARD,
            "ubus call network.interface.lan status": _LAN_STATUS,
        }
    )
    device = _monitor(runner).fetch_status(_device())

    assert device.status is DeviceStatus.CONNECTED
    assert device.firmware == "23.05.3"
    assert device.model == "TP-Link ER605 (mock)"
    assert device.uptime_seconds == 4242


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


def test_fetch_clients_from_dhcp_leases() -> None:
    runner = FakeSshRunner({"ubus call dhcp ipv4leases": _LEASES})
    clients = _monitor(runner).fetch_clients(_device())

    assert [str(c.mac) for c in clients] == ["1C:61:B4:00:11:22", "A4:83:E7:00:33:44"]
    assert clients[0].name == "desktop"
    assert clients[0].connection is ConnectionType.WIRED
    assert str(clients[0].ip) == "192.168.50.20"


def test_fetch_clients_falls_back_to_lease_file_without_odhcpd() -> None:
    leases = (
        "1700000000 1c:61:b4:00:11:22 192.168.50.20 desktop 01:1c:61:b4:00:11:22\n"
        "1700000100 a4:83:e7:00:33:44 192.168.50.21 * 01:a4:83:e7:00:33:44\n"
    )
    runner = FakeSshRunner(
        {"cat /tmp/dhcp.leases": leases},
        errors=["ubus call dhcp ipv4leases"],
    )
    clients = _monitor(runner).fetch_clients(_device())

    assert [str(c.mac) for c in clients] == ["1C:61:B4:00:11:22", "A4:83:E7:00:33:44"]
    assert clients[0].name == "desktop"
    assert str(clients[0].ip) == "192.168.50.20"
    # Hostname "*" in the lease file falls back to the MAC as the display name.
    assert clients[1].name == "A4:83:E7:00:33:44"


def test_fetch_config_is_authoritative_and_clears_stale_entries() -> None:
    # The device reports no bridge-vlans, no wireless and no ports, but the
    # inventory still carries stale values. A re-read is the single source of
    # truth, so the returned device must come back empty, not keep the old data.
    from sdnman.domain.entities import SwitchPort, Vlan

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
