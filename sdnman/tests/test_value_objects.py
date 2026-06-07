"""Tests for domain value objects."""

from __future__ import annotations

import pytest

from sdnman.domain.value_objects import (
    DataVolume,
    IpAddress,
    MacAddress,
    Throughput,
)


def test_mac_address_normalised():
    assert str(MacAddress("ac-1f-6b-00-00-01")) == "AC:1F:6B:00:00:01"


@pytest.mark.parametrize("bad", ["", "zz:zz:zz:zz:zz:zz", "12:34:56"])
def test_mac_address_rejects_invalid(bad):
    with pytest.raises(ValueError):
        MacAddress(bad)


def test_ip_address_version():
    assert IpAddress("192.168.1.1").version == 4
    assert IpAddress("::1").version == 6


def test_ip_address_rejects_invalid():
    with pytest.raises(ValueError):
        IpAddress("999.1.1.1")


def test_throughput_humanize():
    assert Throughput(0).humanize() == "0 B/s"
    assert Throughput(2048).humanize() == "2.0 KB/s"


def test_data_volume_humanize():
    assert DataVolume(0).humanize() == "0 Bytes"
    assert DataVolume(1536).humanize() == "1.5 KB"


def test_negative_values_rejected():
    with pytest.raises(ValueError):
        Throughput(-1)
    with pytest.raises(ValueError):
        DataVolume(-1)
