"""Tests for the SSH transcript ring buffer and its capture in runners."""

from __future__ import annotations

import logging

from hsnc.devices.ssh_transport import (
    FakeSshRunner,
    PersistentRunnerRegistry,
    SshConnectionResolver,
    SshConnectionSettings,
    SshTarget,
    SshTranscript,
    apply_paramiko_global_debug,
)
from hsnc.entities import Device
from hsnc.enums import DeviceKind
from hsnc.value_objects import IpAddress, MacAddress


def test_transcript_records_kind_and_text():
    t = SshTranscript()
    t.record("sent", "uci show network")
    t.record("recv", "network.lan=interface")
    lines = t.lines()
    assert [(e.kind, e.text) for e in lines] == [
        ("sent", "uci show network"),
        ("recv", "network.lan=interface"),
    ]
    assert all(e.ts > 0 for e in lines)


def test_transcript_splits_multiline_and_drops_trailing_newline():
    t = SshTranscript()
    t.record("recv", "line-1\nline-2\n")
    assert [e.text for e in t.lines()] == ["line-1", "line-2"]


def test_transcript_ignores_empty_text():
    t = SshTranscript()
    t.record("recv", "")
    assert t.lines() == []


def test_transcript_is_bounded():
    t = SshTranscript(maxlen=3)
    for i in range(10):
        t.record("recv", f"line-{i}")
    texts = [e.text for e in t.lines()]
    assert texts == ["line-7", "line-8", "line-9"]


def test_transcript_limit_returns_tail():
    t = SshTranscript()
    for i in range(5):
        t.record("recv", f"line-{i}")
    assert [e.text for e in t.lines(limit=2)] == ["line-3", "line-4"]


def test_fake_runner_records_run():
    runner = FakeSshRunner({"uci show network": "network.lan=interface"})
    runner.run("uci show network")
    kinds = [(e.kind, e.text) for e in runner.transcript.lines()]
    assert ("sent", "uci show network") in kinds
    assert ("recv", "network.lan=interface") in kinds


def test_fake_runner_records_shell():
    runner = FakeSshRunner(shell_output="banner\nok")
    runner.run_shell(["show version", "show running-config"])
    texts = [e.text for e in runner.transcript.lines()]
    assert "show version" in texts
    assert "show running-config" in texts
    assert "banner" in texts


def test_fake_runner_records_error():
    runner = FakeSshRunner(errors=["reboot"])
    try:
        runner.run("reboot now")
    except Exception:
        pass
    assert any(e.kind == "error" for e in runner.transcript.lines())


def test_registry_peek_does_not_create():
    registry = PersistentRunnerRegistry()
    target = SshTarget(host="10.0.0.1", port=22, username="root", password="x")
    assert registry.peek(target) is None
    runner = registry.get(target)
    assert registry.peek(target) is runner


# --- transcript debug mirroring -------------------------------------------------


def test_transcript_debug_mirrors_to_logger(caplog):
    t = SshTranscript(debug=True, label="gateway-1")
    with caplog.at_level(logging.DEBUG, logger="hsnc.ssh.transcript"):
        t.record("recv", "line-1\nline-2")
    messages = [r.getMessage() for r in caplog.records]
    assert "[gateway-1] recv | line-1" in messages
    assert "[gateway-1] recv | line-2" in messages


def test_transcript_debug_off_does_not_log(caplog):
    t = SshTranscript(debug=False, label="gateway-1")
    with caplog.at_level(logging.DEBUG, logger="hsnc.ssh.transcript"):
        t.record("recv", "secret-output")
    assert caplog.records == []


# --- env parsing of debug flags -------------------------------------------------


def test_from_env_parses_global_debug_flags():
    settings = SshConnectionSettings.from_env(
        {"HSNC_SSH_DEBUG": "1", "HSNC_SSH_TRANSCRIPT_DEBUG": "yes"}
    )
    assert settings.paramiko_debug is True
    assert settings.transcript_debug is True


def test_from_env_debug_flags_default_false():
    settings = SshConnectionSettings.from_env({})
    assert settings.paramiko_debug is False
    assert settings.transcript_debug is False
    assert settings.device_paramiko_debug == {}
    assert settings.device_transcript_debug == {}


def test_from_env_per_device_debug_flags():
    settings = SshConnectionSettings.from_env(
        {
            "HSNC_DEVICE_GATEWAY_1_SSH_DEBUG": "1",
            "HSNC_DEVICE_SWITCH_2_SSH_DEBUG": "0",
            "HSNC_DEVICE_GATEWAY_1_SSH_TRANSCRIPT_DEBUG": "on",
        }
    )
    assert settings.device_paramiko_debug == {"GATEWAY_1": True, "SWITCH_2": False}
    assert settings.device_transcript_debug == {"GATEWAY_1": True}


def test_from_env_disambiguates_transcript_from_paramiko_suffix():
    # The transcript key must NOT leak into the paramiko map.
    settings = SshConnectionSettings.from_env(
        {"HSNC_DEVICE_GATEWAY_1_SSH_TRANSCRIPT_DEBUG": "1"}
    )
    assert settings.device_transcript_debug == {"GATEWAY_1": True}
    assert settings.device_paramiko_debug == {}


# --- resolver stamping ----------------------------------------------------------


def _device(device_id: str = "gateway-1") -> Device:
    return Device(
        id=device_id,
        name="ER605",
        kind=DeviceKind.GATEWAY,
        mac=MacAddress("AC:1F:6B:A0:00:01"),
        model="TP-Link ER605 (OpenWrt)",
        ip=IpAddress("192.168.50.254"),
    )


def test_resolver_stamps_global_debug_flags():
    resolver = SshConnectionResolver(
        SshConnectionSettings(transcript_debug=True, paramiko_debug=True)
    )
    target = resolver.resolve(_device())
    assert target.debug_transcript is True
    assert target.debug_paramiko is True
    assert target.label == "gateway-1"


def test_resolver_per_device_overrides_global_on_to_off():
    resolver = SshConnectionResolver(
        SshConnectionSettings(
            paramiko_debug=True,
            device_paramiko_debug={"GATEWAY_1": False},
        )
    )
    target = resolver.resolve(_device())
    assert target.debug_paramiko is False


def test_resolver_per_device_overrides_global_off_to_on():
    resolver = SshConnectionResolver(
        SshConnectionSettings(
            transcript_debug=False,
            device_transcript_debug={"GATEWAY_1": True},
        )
    )
    target = resolver.resolve(_device())
    assert target.debug_transcript is True


def test_resolver_default_flags_off():
    resolver = SshConnectionResolver(SshConnectionSettings())
    target = resolver.resolve(_device())
    assert target.debug_transcript is False
    assert target.debug_paramiko is False


# --- global paramiko logger level ----------------------------------------------


def test_apply_paramiko_global_debug_toggles_base_logger():
    try:
        apply_paramiko_global_debug(True)
        assert logging.getLogger("paramiko").level == logging.DEBUG
        apply_paramiko_global_debug(False)
        assert logging.getLogger("paramiko").level == logging.CRITICAL
    finally:
        apply_paramiko_global_debug(False)


def test_resolver_construction_applies_global_paramiko_level():
    try:
        SshConnectionResolver(SshConnectionSettings(paramiko_debug=True))
        assert logging.getLogger("paramiko").level == logging.DEBUG
        SshConnectionResolver(SshConnectionSettings(paramiko_debug=False))
        assert logging.getLogger("paramiko").level == logging.CRITICAL
    finally:
        apply_paramiko_global_debug(False)
