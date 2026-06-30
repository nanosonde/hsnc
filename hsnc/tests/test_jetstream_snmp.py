"""Tests for the JetStream SNMPv3 monitoring provider."""

from __future__ import annotations

from hsnc.devices.jetstream.snmp_monitoring import (
    JetStreamSnmpMonitoringProvider,
    SnmpConnectionSettings,
    SnmpTarget,
    _mac_from_fdb_oid,
)
from hsnc.entities import Device, MonitoringConfig, MonitoringTarget
from hsnc.enums import ConnectionType, DeviceKind, DeviceStatus
from hsnc.value_objects import IpAddress

_SYS = {
    "1.3.6.1.2.1.1.1.0": "JetStream Gigabit Smart Switch",
    "1.3.6.1.2.1.1.3.0": "360000",  # 3600s in TimeTicks (1/100s)
    "1.3.6.1.2.1.1.5.0": "core-switch",
}

_FDB = [
    ("1.3.6.1.2.1.17.4.3.1.2.0.17.34.170.187.1", "5"),
    ("1.3.6.1.2.1.17.4.3.1.2.0.17.34.170.187.3", "7"),
]


class _FakeSnmpClient:
    def __init__(self, target: SnmpTarget) -> None:
        self.target = target

    def get(self, oids: list[str]) -> dict[str, str]:
        return {oid: _SYS[oid] for oid in oids if oid in _SYS}

    def walk(self, oid: str) -> list[tuple[str, str]]:
        return list(_FDB)


def _device(target: MonitoringTarget | None = None, ip: str = "10.0.0.6") -> Device:
    return Device(
        id="switch-1",
        name="SW One",
        kind=DeviceKind.SWITCH,
        ip=IpAddress(ip),
        monitoring=MonitoringConfig(target=target),
    )


def _provider() -> JetStreamSnmpMonitoringProvider:
    return JetStreamSnmpMonitoringProvider(
        settings=SnmpConnectionSettings(), client_factory=_FakeSnmpClient
    )


def test_mac_from_fdb_oid() -> None:
    mac = _mac_from_fdb_oid("1.3.6.1.2.1.17.4.3.1.2.0.17.34.170.187.1")
    assert str(mac) == "00:11:22:AA:BB:01"


def test_mac_from_fdb_oid_rejects_short_oid() -> None:
    assert _mac_from_fdb_oid("1.3.6.1") is None


def test_fetch_status_parses_sys_group() -> None:
    result = _provider().fetch_status(_device())
    assert result.status is DeviceStatus.CONNECTED
    assert result.name == "core-switch"
    assert result.model == "JetStream Gigabit Smart Switch"
    assert result.uptime_seconds == 3600


def test_fetch_clients_walks_fdb() -> None:
    clients = _provider().fetch_clients(_device())
    assert {str(c.mac) for c in clients} == {"00:11:22:AA:BB:01", "00:11:22:AA:BB:03"}
    assert all(c.connection is ConnectionType.WIRED for c in clients)
    first = next(c for c in clients if str(c.mac) == "00:11:22:AA:BB:01")
    assert first.ap_or_port == "Port 5"


def test_settings_resolve_uses_endpoint_and_port() -> None:
    settings = SnmpConnectionSettings(port=161)
    target = settings.resolve(
        _device(MonitoringTarget(endpoint="10.5.5.5", port=1610))
    )
    assert target.host == "10.5.5.5"
    assert target.port == 1610


def test_settings_resolve_parses_host_port_in_endpoint() -> None:
    settings = SnmpConnectionSettings()
    target = settings.resolve(_device(MonitoringTarget(endpoint="10.5.5.5:1620")))
    assert target.host == "10.5.5.5"
    assert target.port == 1620


def test_settings_resolve_derives_host_from_ip() -> None:
    settings = SnmpConnectionSettings()
    target = settings.resolve(_device())
    assert target.host == "10.0.0.6"
    assert target.port == 161


def test_settings_from_env_global_and_per_device() -> None:
    settings = SnmpConnectionSettings.from_env(
        {
            "HSNC_SNMP_USER": "monitor",
            "HSNC_SNMP_AUTH_KEY": "authpass",
            "HSNC_SNMP_PRIV_KEY": "privpass",
            "HSNC_SNMP_PORT": "1161",
            "HSNC_DEVICE_SWITCH_1_SNMP_USER": "switchuser",
            "HSNC_DEVICE_SWITCH_1_SNMP_PORT": "2161",
        }
    )
    assert settings.credentials.user == "monitor"
    assert settings.port == 1161
    target = settings.resolve(_device())
    assert target.credentials.user == "switchuser"
    assert target.port == 2161
