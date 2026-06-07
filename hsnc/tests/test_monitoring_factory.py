"""Tests for strict source-based monitoring provider selection."""

from __future__ import annotations

from hsnc.devices.jetstream.snmp_monitoring import JetStreamSnmpMonitoringProvider
from hsnc.devices.jetstream.ssh_monitoring import JetStreamSshMonitoringProvider
from hsnc.devices.monitoring import (
    DefaultMonitoringProviderFactory,
    MockMonitoringProvider,
    NullMonitoringProvider,
)
from hsnc.devices.openwrt.prometheus_monitoring import OpenWrtPrometheusMonitoringProvider
from hsnc.devices.openwrt.ssh_monitoring import OpenWrtSshMonitoringProvider
from hsnc.entities import Device, MonitoringConfig, SecondaryMonitoring
from hsnc.enums import DeviceKind


def _device(kind: DeviceKind, monitoring: MonitoringConfig | None = None) -> Device:
    return Device(id="d1", name="d1", kind=kind, monitoring=monitoring)


def _factory() -> DefaultMonitoringProviderFactory:
    return DefaultMonitoringProviderFactory(use_mock=False)


def test_mock_mode_always_mock() -> None:
    factory = DefaultMonitoringProviderFactory(use_mock=True)
    provider = factory.for_device(_device(DeviceKind.SWITCH))
    assert isinstance(provider, MockMonitoringProvider)


def test_primary_switch_uses_jetstream_ssh() -> None:
    provider = _factory().for_device(
        _device(DeviceKind.SWITCH, MonitoringConfig(source="primary"))
    )
    assert isinstance(provider, JetStreamSshMonitoringProvider)


def test_primary_gateway_uses_openwrt_ssh() -> None:
    provider = _factory().for_device(
        _device(DeviceKind.GATEWAY, MonitoringConfig(source="primary"))
    )
    assert isinstance(provider, OpenWrtSshMonitoringProvider)


def test_default_source_is_primary() -> None:
    provider = _factory().for_device(_device(DeviceKind.ACCESS_POINT, None))
    assert isinstance(provider, OpenWrtSshMonitoringProvider)


def test_source_none_uses_null() -> None:
    provider = _factory().for_device(
        _device(DeviceKind.SWITCH, MonitoringConfig(source="none"))
    )
    assert isinstance(provider, NullMonitoringProvider)


def test_secondary_prometheus_uses_prometheus_provider() -> None:
    provider = _factory().for_device(
        _device(
            DeviceKind.ACCESS_POINT,
            MonitoringConfig(source="secondary", secondary=SecondaryMonitoring(type="prometheus")),
        )
    )
    assert isinstance(provider, OpenWrtPrometheusMonitoringProvider)


def test_secondary_snmp_uses_snmp_provider() -> None:
    provider = _factory().for_device(
        _device(
            DeviceKind.SWITCH,
            MonitoringConfig(source="secondary", secondary=SecondaryMonitoring(type="snmp")),
        )
    )
    assert isinstance(provider, JetStreamSnmpMonitoringProvider)


def test_secondary_missing_type_falls_back_to_null(caplog) -> None:
    provider = _factory().for_device(
        _device(DeviceKind.SWITCH, MonitoringConfig(source="secondary", secondary=None))
    )
    assert isinstance(provider, NullMonitoringProvider)
