"""Tests for the SSH transcript ring buffer and its capture in runners."""

from __future__ import annotations

from hsnc.devices.ssh_transport import (
    FakeSshRunner,
    PersistentRunnerRegistry,
    SshTarget,
    SshTranscript,
)


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
