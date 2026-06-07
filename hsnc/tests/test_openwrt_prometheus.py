"""Tests for the OpenWrt Prometheus (secondary) monitoring provider."""

from __future__ import annotations

from hsnc.devices.openwrt.prometheus_monitoring import (
    OpenWrtPrometheusMonitoringProvider,
    PrometheusSettings,
    PrometheusTarget,
    parse_metrics,
)
from hsnc.entities import Device, MonitoringConfig, SecondaryMonitoring
from hsnc.enums import ConnectionType, DeviceKind, DeviceStatus
from hsnc.value_objects import IpAddress

_METRICS = """\
# HELP node_uname_info Labeled system information.
# TYPE node_uname_info gauge
node_uname_info{machine="x86_64",release="5.15.150",sysname="Linux"} 1
node_boot_time_seconds 1.0e3
node_time_seconds 4600
wifi_station_signal_dbm{ifname="wlan0",mac="AA:BB:CC:00:00:01"} -55
wifi_station_signal_dbm{ifname="wlan0",mac="aa:bb:cc:00:00:01"} -54
wifi_network_bitrate{vap="wlan1",mac="AA:BB:CC:00:00:02"} 866
"""


def _device(secondary: SecondaryMonitoring | None = None, ip: str = "10.0.0.5") -> Device:
    return Device(
        id="ap-1",
        name="AP One",
        kind=DeviceKind.ACCESS_POINT,
        ip=IpAddress(ip),
        monitoring=MonitoringConfig(source="secondary", secondary=secondary),
    )


def test_parse_metrics_skips_comments_and_parses_labels() -> None:
    samples = parse_metrics(_METRICS)
    names = {s.name for s in samples}
    assert "node_uname_info" in names
    uname = next(s for s in samples if s.name == "node_uname_info")
    assert uname.labels["machine"] == "x86_64"
    assert uname.labels["release"] == "5.15.150"


def test_fetch_status_reports_uptime_from_boot_time() -> None:
    provider = OpenWrtPrometheusMonitoringProvider(
        settings=PrometheusSettings(), fetcher=lambda target: _METRICS
    )
    result = provider.fetch_status(_device(SecondaryMonitoring(type="prometheus")))
    assert result.status is DeviceStatus.CONNECTED
    assert result.uptime_seconds == 3600  # 4600 - 1000
    assert result.model == "x86_64"
    assert result.firmware == "5.15.150"


def test_fetch_status_falls_back_to_node_uptime_seconds() -> None:
    provider = OpenWrtPrometheusMonitoringProvider(
        settings=PrometheusSettings(),
        fetcher=lambda target: "node_uptime_seconds 1234\n",
    )
    result = provider.fetch_status(_device(SecondaryMonitoring(type="prometheus")))
    assert result.uptime_seconds == 1234


def test_fetch_clients_dedupes_by_mac() -> None:
    provider = OpenWrtPrometheusMonitoringProvider(
        settings=PrometheusSettings(), fetcher=lambda target: _METRICS
    )
    clients = provider.fetch_clients(_device(SecondaryMonitoring(type="prometheus")))
    macs = {str(c.mac) for c in clients}
    assert macs == {"AA:BB:CC:00:00:01", "AA:BB:CC:00:00:02"}
    assert all(c.connection is ConnectionType.WIRELESS for c in clients)
    ap = next(c for c in clients if str(c.mac) == "AA:BB:CC:00:00:01")
    assert ap.ap_or_port == "wlan0"


def test_settings_resolve_uses_configured_endpoint() -> None:
    captured: list[PrometheusTarget] = []

    def fetcher(target: PrometheusTarget) -> str:
        captured.append(target)
        return ""

    settings = PrometheusSettings(token="global-token")
    provider = OpenWrtPrometheusMonitoringProvider(settings=settings, fetcher=fetcher)
    device = _device(
        SecondaryMonitoring(type="prometheus", endpoint="http://10.9.9.9:9100/metrics")
    )
    provider.fetch_status(device)
    assert captured[0].url == "http://10.9.9.9:9100/metrics"
    assert captured[0].token == "global-token"


def test_settings_resolve_derives_endpoint_from_ip() -> None:
    captured: list[PrometheusTarget] = []
    settings = PrometheusSettings()
    provider = OpenWrtPrometheusMonitoringProvider(
        settings=settings, fetcher=lambda t: captured.append(t) or ""
    )
    provider.fetch_status(_device(SecondaryMonitoring(type="prometheus")))
    assert captured[0].url == "http://10.0.0.5:9100/metrics"


def test_settings_from_env_per_device_token() -> None:
    settings = PrometheusSettings.from_env(
        {
            "HSNC_PROMETHEUS_TOKEN": "global",
            "HSNC_DEVICE_AP_1_PROMETHEUS_TOKEN": "per-device",
        }
    )
    target = settings.resolve(_device(SecondaryMonitoring(type="prometheus")))
    assert target.token == "per-device"
