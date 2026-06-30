"""Tests for platform/kind-based monitoring provider selection."""

from __future__ import annotations

from hsnc.devices.jetstream.snmp_monitoring import JetStreamSnmpMonitoringProvider
from hsnc.devices.monitoring import (
    DefaultMonitoringProviderFactory,
    MockMonitoringProvider,
    NullMonitoringProvider,
)
from hsnc.devices.openwrt.prometheus_monitoring import OpenWrtPrometheusMonitoringProvider
from hsnc.entities import Device, MonitoringConfig
from hsnc.enums import DeviceKind


def _device(kind: DeviceKind, monitoring: MonitoringConfig | None = None) -> Device:
    return Device(id="d1", name="d1", kind=kind, monitoring=monitoring)


def _factory() -> DefaultMonitoringProviderFactory:
    return DefaultMonitoringProviderFactory(use_mock=False)


def test_mock_mode_always_mock() -> None:
    factory = DefaultMonitoringProviderFactory(use_mock=True)
    provider = factory.for_device(_device(DeviceKind.SWITCH))
    assert isinstance(provider, MockMonitoringProvider)


def test_switch_uses_jetstream_snmp() -> None:
    provider = _factory().for_device(_device(DeviceKind.SWITCH))
    assert isinstance(provider, JetStreamSnmpMonitoringProvider)


def test_gateway_uses_openwrt_prometheus() -> None:
    provider = _factory().for_device(_device(DeviceKind.GATEWAY))
    assert isinstance(provider, OpenWrtPrometheusMonitoringProvider)


def test_access_point_uses_openwrt_prometheus() -> None:
    provider = _factory().for_device(_device(DeviceKind.ACCESS_POINT))
    assert isinstance(provider, OpenWrtPrometheusMonitoringProvider)


def test_monitoring_disabled_uses_null() -> None:
    provider = _factory().for_device(
        _device(DeviceKind.SWITCH, MonitoringConfig(enabled=False))
    )
    assert isinstance(provider, NullMonitoringProvider)


def test_enabled_true_is_default() -> None:
    provider = _factory().for_device(
        _device(DeviceKind.SWITCH, MonitoringConfig(enabled=True))
    )
    assert isinstance(provider, JetStreamSnmpMonitoringProvider)


def test_no_monitoring_config_still_polls() -> None:
    provider = _factory().for_device(_device(DeviceKind.ACCESS_POINT, None))
    assert isinstance(provider, OpenWrtPrometheusMonitoringProvider)
