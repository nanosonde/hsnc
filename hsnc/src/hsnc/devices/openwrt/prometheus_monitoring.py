"""OpenWrt runtime monitoring over a Prometheus exporter — secondary source.

Polls an OpenWrt device's Prometheus node-exporter endpoint (e.g.
``prometheus-node-exporter-lua``) instead of scraping over SSH. This is the
*secondary* monitoring connection, selected per device via
``monitoring.source: secondary`` with ``monitoring.secondary.type: prometheus``.

Only the non-secret endpoint lives in ``devices.yaml``; an optional bearer token
comes from the environment (``HSNC_PROMETHEUS_TOKEN`` or the per-device
``HSNC_DEVICE_<ID>_PROMETHEUS_TOKEN``).

Client enumeration relies on the exporter's wifi collector exposing per-station
metrics carrying a ``mac`` label; when those are absent the provider reports the
device status only, with no clients.
"""

from __future__ import annotations

import os
import re
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, replace

from ...entities import Client, Device
from ...enums import ConnectionType, DeviceStatus
from ...interfaces import MonitoringProvider
from ...value_objects import MacAddress
from ..ssh_transport import _normalise_id

# Prometheus text-exposition sample: ``name{labels} value [timestamp]``.
_SAMPLE_RE = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)(?:\{(?P<labels>.*)\})?\s+(?P<value>\S+)"
)
_LABEL_RE = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:\\.|[^"\\])*)"')

_DEFAULT_PORT = 9100
_DEFAULT_PATH = "/metrics"


@dataclass(frozen=True)
class PrometheusTarget:
    """Resolved Prometheus scrape target for one device."""

    url: str
    token: str = ""
    verify_tls: bool = True


@dataclass(frozen=True)
class PrometheusSettings:
    """Environment-derived Prometheus options (secrets only — endpoints are
    configured per device in ``devices.yaml``)."""

    token: str = ""
    device_tokens: dict[str, str] | None = None
    verify_tls: bool = True

    @staticmethod
    def from_env(environ: dict[str, str] | None = None) -> PrometheusSettings:
        env = environ if environ is not None else os.environ
        device_tokens = {
            key[len("HSNC_DEVICE_"):-len("_PROMETHEUS_TOKEN")]: value
            for key, value in env.items()
            if key.startswith("HSNC_DEVICE_") and key.endswith("_PROMETHEUS_TOKEN")
        }
        verify = env.get("HSNC_PROMETHEUS_VERIFY_TLS", "1") not in ("0", "false", "False")
        return PrometheusSettings(
            token=env.get("HSNC_PROMETHEUS_TOKEN", ""),
            device_tokens=device_tokens,
            verify_tls=verify,
        )

    def resolve(self, device: Device) -> PrometheusTarget:
        secondary = device.monitoring.secondary if device.monitoring else None
        url = (secondary.endpoint if secondary and secondary.endpoint else "").strip()
        if not url:
            if device.ip is None:
                raise ValueError(
                    f"device {device.id!r} has no Prometheus endpoint or IP to derive one"
                )
            url = f"http://{device.ip}:{_DEFAULT_PORT}{_DEFAULT_PATH}"
        tokens = self.device_tokens or {}
        token = tokens.get(_normalise_id(device.id), self.token)
        return PrometheusTarget(url=url, token=token, verify_tls=self.verify_tls)


def _default_fetcher(target: PrometheusTarget, timeout: float = 10.0) -> str:
    request = urllib.request.Request(target.url)  # noqa: S310 - operator-configured URL
    if target.token:
        request.add_header("Authorization", f"Bearer {target.token}")
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
        return response.read().decode("utf-8", "replace")


PrometheusFetcher = Callable[[PrometheusTarget], str]


@dataclass(frozen=True)
class _Sample:
    name: str
    labels: dict[str, str]
    value: float


def _parse_labels(raw: str | None) -> dict[str, str]:
    if not raw:
        return {}
    return {m.group(1): m.group(2) for m in _LABEL_RE.finditer(raw)}


def parse_metrics(text: str) -> list[_Sample]:
    """Parse Prometheus text-exposition output into samples (comments skipped)."""
    samples: list[_Sample] = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = _SAMPLE_RE.match(line)
        if not match:
            continue
        try:
            value = float(match.group("value"))
        except ValueError:
            continue
        samples.append(
            _Sample(match.group("name"), _parse_labels(match.group("labels")), value)
        )
    return samples


class OpenWrtPrometheusMonitoringProvider(MonitoringProvider):
    """Reads OpenWrt runtime state from a Prometheus node-exporter endpoint."""

    def __init__(
        self,
        settings: PrometheusSettings | None = None,
        fetcher: PrometheusFetcher = _default_fetcher,
    ) -> None:
        self._settings = settings or PrometheusSettings.from_env()
        self._fetcher = fetcher

    def _samples(self, device: Device) -> list[_Sample]:
        target = self._settings.resolve(device)
        return parse_metrics(self._fetcher(target))

    def fetch_status(self, device: Device) -> Device:
        samples = self._samples(device)
        by_name: dict[str, _Sample] = {s.name: s for s in samples}
        uptime = self._uptime_seconds(by_name)
        model, firmware = self._uname(samples)
        return replace(
            device,
            status=DeviceStatus.CONNECTED,
            model=model or device.model,
            firmware=firmware or device.firmware,
            uptime_seconds=uptime if uptime is not None else device.uptime_seconds,
        )

    def fetch_clients(self, device: Device) -> list[Client]:
        samples = self._samples(device)
        seen: dict[str, str] = {}
        for sample in samples:
            mac = sample.labels.get("mac")
            if not mac or ":" not in mac:
                continue
            ap = sample.labels.get("ifname") or sample.labels.get("vap") or device.name
            seen.setdefault(mac.lower(), ap)
        clients: list[Client] = []
        for mac, ap in seen.items():
            mac_obj = MacAddress(mac)
            clients.append(
                Client(
                    id=f"{device.id}-{mac_obj}",
                    name=str(mac_obj),
                    mac=mac_obj,
                    connection=ConnectionType.WIRELESS,
                    status=DeviceStatus.CONNECTED,
                    ap_or_port=ap,
                    site_id=device.site_id,
                )
            )
        return clients

    @staticmethod
    def _uptime_seconds(by_name: dict[str, _Sample]) -> int | None:
        if "node_time_seconds" in by_name and "node_boot_time_seconds" in by_name:
            delta = by_name["node_time_seconds"].value - by_name["node_boot_time_seconds"].value
            return int(delta) if delta >= 0 else 0
        if "node_uptime_seconds" in by_name:
            return int(by_name["node_uptime_seconds"].value)
        return None

    @staticmethod
    def _uname(samples: list[_Sample]) -> tuple[str, str]:
        for sample in samples:
            if sample.name == "node_uname_info":
                machine = sample.labels.get("machine", "")
                release = sample.labels.get("release", "")
                return machine, release
        return "", ""
