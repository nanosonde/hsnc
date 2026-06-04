"""Immutable value objects with self-validation.

Value objects have no identity; equality is based on their value. They validate
their invariants at construction time so the rest of the domain can trust them.
"""

from __future__ import annotations

import ipaddress
import re
from dataclasses import dataclass

_MAC_RE = re.compile(r"^[0-9A-Fa-f]{2}(:[0-9A-Fa-f]{2}){5}$")


@dataclass(frozen=True, slots=True)
class MacAddress:
    """A 48-bit hardware address, normalised to upper-case colon notation."""

    value: str

    def __post_init__(self) -> None:
        normalised = self._normalise(self.value)
        if not _MAC_RE.match(normalised):
            raise ValueError(f"Invalid MAC address: {self.value!r}")
        # frozen dataclass: assign through object.__setattr__
        object.__setattr__(self, "value", normalised)

    @staticmethod
    def _normalise(raw: str) -> str:
        cleaned = raw.strip().replace("-", ":").replace(".", ":")
        return cleaned.upper()

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class IpAddress:
    """An IPv4 or IPv6 address."""

    value: str

    def __post_init__(self) -> None:
        try:
            ipaddress.ip_address(self.value)
        except ValueError as exc:
            raise ValueError(f"Invalid IP address: {self.value!r}") from exc

    @property
    def version(self) -> int:
        return ipaddress.ip_address(self.value).version

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class Throughput:
    """A point-in-time transfer rate expressed in bytes per second."""

    bytes_per_second: float = 0.0

    def __post_init__(self) -> None:
        if self.bytes_per_second < 0:
            raise ValueError("Throughput cannot be negative")

    def humanize(self) -> str:
        units = ["B/s", "KB/s", "MB/s", "GB/s", "TB/s"]
        value = float(self.bytes_per_second)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.0f} {unit}" if unit == "B/s" else f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} {units[-1]}"


@dataclass(frozen=True, slots=True)
class DataVolume:
    """A cumulative byte counter (e.g. total download/upload)."""

    bytes: int = 0

    def __post_init__(self) -> None:
        if self.bytes < 0:
            raise ValueError("DataVolume cannot be negative")

    def humanize(self) -> str:
        units = ["Bytes", "KB", "MB", "GB", "TB"]
        value = float(self.bytes)
        for unit in units:
            if value < 1024 or unit == units[-1]:
                return f"{value:.0f} {unit}" if unit == "Bytes" else f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} {units[-1]}"
