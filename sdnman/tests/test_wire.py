"""Tests for the REST wire contract (serialization + error envelope)."""

from __future__ import annotations

import json
from datetime import datetime

from sdnman.application.dtos import (
    DeviceDetail,
    DeviceRow,
    PagedClients,
    PortRow,
    VlanRow,
)
from sdnman.application.use_cases.edit_device_config import (
    ConfigEditError,
    DeviceNotFoundError,
)
from sdnman.application.wire import (
    DEFAULT_ERROR_STATUS,
    error_envelope,
    status_for_exception,
    to_jsonable,
)
from sdnman.domain.entities import ApplyEvent, ApplyOutcome, FieldChange
from sdnman.infrastructure.devices.ssh_transport import SshError


def test_to_jsonable_serializes_nested_dataclass_to_json_safe_dict():
    detail = DeviceDetail(
        row=DeviceRow(
            id="switch-1",
            name="TL-SG2210P",
            kind="switch",
            model="",
            mac="B0:4E:26:00:00:10",
            ip="192.168.50.2",
            status="connected",
            firmware="",
            uptime="26m",
            client_count=6,
        ),
        ports=[PortRow(1, "Port 1", True, "access", 1, [], True, 1000)],
        vlans=[VlanRow(10, "MGMT", "192.168.10.0/24")],
        ssids=["home", "guest"],
    )

    encoded = to_jsonable(detail)
    # Must be JSON-serializable and round-trip without loss of structure.
    assert json.loads(json.dumps(encoded)) == encoded
    assert encoded["row"]["name"] == "TL-SG2210P"
    assert encoded["ports"][0]["mode"] == "access"
    assert encoded["vlans"][0]["vlan_id"] == 10
    assert encoded["ssids"] == ["home", "guest"]


def test_to_jsonable_omits_computed_properties():
    paged = PagedClients(rows=[], page=1, page_size=20, total=0)
    encoded = to_jsonable(paged)
    assert set(encoded) == {"rows", "page", "page_size", "total"}
    assert "total_pages" not in encoded


def test_to_jsonable_encodes_datetime_as_isoformat():
    event = ApplyEvent(
        applied_at=datetime(2026, 6, 7, 12, 30, 45),
        username="admin",
        ok=True,
        outcomes=[
            ApplyOutcome(
                device_id="switch-1",
                device_name="TL-SG2210P",
                ok=True,
                message="",
                changes=[FieldChange("hostname", "old", "new")],
            )
        ],
        action="apply",
        id=3,
    )

    encoded = to_jsonable(event)
    assert encoded["applied_at"] == "2026-06-07T12:30:45"
    assert encoded["id"] == 3
    assert encoded["outcomes"][0]["changes"][0]["field"] == "hostname"
    assert json.loads(json.dumps(encoded)) == encoded


def test_status_for_exception_maps_known_types():
    assert status_for_exception(DeviceNotFoundError("nope")) == 404
    assert status_for_exception(ConfigEditError("bad")) == 400
    assert status_for_exception(ValueError("bad")) == 400
    assert status_for_exception(SshError("down")) == 502


def test_status_for_exception_defaults_to_500():
    assert status_for_exception(RuntimeError("boom")) == DEFAULT_ERROR_STATUS


def test_error_envelope_carries_type_and_message():
    envelope = error_envelope(DeviceNotFoundError("device 'x' not found"))
    assert envelope == {
        "error": {"type": "DeviceNotFoundError", "message": "device 'x' not found"}
    }
