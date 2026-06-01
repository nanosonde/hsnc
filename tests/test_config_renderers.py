"""Tests for platform config renderers and the command-level diff."""

from __future__ import annotations

import copy

from omada_clone.application.use_cases.config_diff import GetConfigDiff
from omada_clone.domain.entities import Device, SwitchPort, Vlan
from omada_clone.domain.enums import DeviceKind, PortMode
from omada_clone.domain.value_objects import IpAddress, MacAddress
from omada_clone.infrastructure.devices.config_renderers import (
    DefaultConfigRendererFactory,
    JetStreamCliRenderer,
    UciConfigRenderer,
)

from .fakes import FakeAppliedConfigStore


def _jetstream_switch() -> Device:
    return Device(
        id="switch-1",
        name="TL-SG2210P",
        kind=DeviceKind.SWITCH,
        mac=MacAddress("B0:4E:26:00:00:10"),
        model="TP-Link JetStream TL-SG2210P",
        ip=IpAddress("192.168.50.2"),
        vlans=[Vlan(1, "Default"), Vlan(10, "Management")],
        ports=[
            SwitchPort(number=1, mode=PortMode.TRUNK, pvid=1, tagged_vlans=[1, 10]),
            SwitchPort(number=2, mode=PortMode.ACCESS, pvid=10),
        ],
    )


def _openwrt_switch() -> Device:
    return Device(
        id="switch-2",
        name="GS1900-OWRT",
        kind=DeviceKind.SWITCH,
        mac=MacAddress("B0:B2:DC:00:00:30"),
        model="Zyxel GS1900-8 (OpenWrt DSA)",
        ip=IpAddress("192.168.50.4"),
        vlans=[Vlan(1, "Default"), Vlan(30, "IoT")],
        ports=[
            SwitchPort(number=1, mode=PortMode.TRUNK, pvid=1, tagged_vlans=[1, 30]),
            SwitchPort(number=3, mode=PortMode.ACCESS, pvid=30),
        ],
    )


def test_factory_routes_by_platform():
    factory = DefaultConfigRendererFactory()
    assert isinstance(factory.for_device(_jetstream_switch()), JetStreamCliRenderer)
    assert isinstance(factory.for_device(_openwrt_switch()), UciConfigRenderer)
    # gateways/APs advertise OpenWrt and render with uci
    ap = Device(
        id="ap-1",
        name="EAP245",
        kind=DeviceKind.ACCESS_POINT,
        mac=MacAddress("10:27:F5:00:00:20"),
        model="TP-Link EAP245 (OpenWrt)",
        ssids=["HomeNet"],
    )
    assert isinstance(factory.for_device(ap), UciConfigRenderer)


def test_jetstream_renderer_emits_cli_commands():
    cmds = JetStreamCliRenderer().render(_jetstream_switch())
    assert cmds[0] == "configure"
    assert "vlan 10" in cmds
    assert " name Management" in cmds
    assert "interface gigabitEthernet 1/0/2" in cmds
    assert " switchport access vlan 10" in cmds
    assert cmds[-1] == "copy running-config startup-config"


def test_uci_renderer_emits_uci_commands():
    cmds = UciConfigRenderer().render(_openwrt_switch())
    assert cmds[0] == "uci set system.@system[0].hostname='GS1900-OWRT'"
    assert any("network.lan.ipaddr='192.168.50.4'" in c for c in cmds)
    assert any("bridge-vlan[-1].vlan='30'" in c for c in cmds)
    # access port 3 is untagged + PVID member of VLAN 30
    assert any("ports='lan1:t lan3:u*'" in c for c in cmds)
    assert cmds[-1] == "uci commit"


def test_command_diff_marks_added_and_removed_lines(config, devices):
    applied = FakeAppliedConfigStore(devices=copy.deepcopy(devices))
    switch = config.get_device("switch-1")
    switch.vlans.append(Vlan(vlan_id=10, name="Management", subnet="192.168.10.0/24"))

    diff = GetConfigDiff(config, applied, DefaultConfigRendererFactory()).execute()
    modified = next(d for d in diff.devices if d.device_id == "switch-1")

    assert modified.platform == "TP-Link JetStream CLI (SSH)"
    added = [ln.text for ln in modified.command_diff if ln.change == "added"]
    assert "vlan 10" in added
    # unchanged lines are carried as context, not added/removed
    assert any(ln.change == "context" for ln in modified.command_diff)


def test_command_diff_absent_without_renderer(config):
    diff = GetConfigDiff(config, FakeAppliedConfigStore()).execute()
    assert all(d.command_diff == [] for d in diff.devices)
    assert all(d.platform == "" for d in diff.devices)
