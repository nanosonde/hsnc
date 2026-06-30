"""TP-Link JetStream managed-switch adapter over SSH/CLI.

Configuration plane only — runtime/monitoring data lives in
:class:`~hsnc.devices.jetstream.snmp_monitoring.JetStreamSnmpMonitoringProvider`
(SNMPv3). Talks to JetStream switches using the same CLI surface the mock
container emulates:

* :meth:`fetch_config`  — ``show running-config`` parsed into VLANs and ports
* :meth:`push_config`   — :class:`JetStreamCliRenderer` commands fed through one
  interactive shell session (config mode is stateful)

Both reads and writes run through a single interactive shell. These switches
reject one-shot ``exec`` channels (``exec request failed on channel 0``), and
``show running-config`` is only available after ``enable`` raises the session to
privileged EXEC mode, so the read sends ``enable`` then ``show running-config``.
"""

from __future__ import annotations

import logging
import re
from dataclasses import replace

from ...entities import Device, SwitchPort, Vlan
from ...enums import DeviceKind, PortMode
from ...interfaces import DeviceAdapter
from ..ssh_transport import (
    RunnerFactory,
    SshCommandRunner,
    SshConnectionResolver,
    SshError,
    default_runner_factory,
)
from .config_renderer import JetStreamCliRenderer

_RUNNER_LOG = logging.getLogger("hsnc.jetstream")

# JetStream rejects a bad command with a `% <reason>` line but keeps the session
# alive, so a mid-push rejection is otherwise invisible. Match only the specific
# error phrasings (anchored at the start of a stripped line) to avoid tripping on
# config content such as a VLAN name that happens to contain a '%'.
_CLI_ERROR_RE = re.compile(
    r"(?im)^\s*%\s*("
    r"unrecognized command"
    r"|invalid"
    r"|incomplete"
    r"|ambiguous"
    r"|unknown command"
    r"|bad command"
    r")",
)


def _scan_for_errors(output: str) -> str | None:
    """Return the first JetStream CLI error line in ``output``, or ``None``."""
    match = _CLI_ERROR_RE.search(output)
    if match is None:
        return None
    # Report the whole offending line for a useful error message.
    line_start = output.rfind("\n", 0, match.start()) + 1
    line_end = output.find("\n", match.start())
    return output[line_start : line_end if line_end != -1 else None].strip()



class JetStreamCliAdapter(DeviceAdapter):
    """Manages TP-Link JetStream switches via the SSH command-line interface."""

    def __init__(
        self,
        resolver: SshConnectionResolver | None = None,
        runner_factory: RunnerFactory = default_runner_factory,
    ) -> None:
        self._resolver = resolver or SshConnectionResolver()
        self._runner_factory = runner_factory
        self._renderer = JetStreamCliRenderer()

    def supports(self, device: Device) -> bool:
        return device.kind is DeviceKind.SWITCH

    # -- connection helper ---------------------------------------------------
    def _runner(self, device: Device) -> SshCommandRunner:
        return self._runner_factory(self._resolver.resolve(device))

    # -- reads ---------------------------------------------------------------
    def fetch_config(self, device: Device) -> Device:
        runner = self._runner(device)
        # The switch rejects exec channels and gates `show running-config` behind
        # privileged mode, so raise privilege then read inside one shell session.
        with runner:
            raw = runner.run_shell(["enable", "show running-config"])
        hostname, vlans, ports = self._parse_running_config(raw)
        return replace(
            device,
            name=hostname or device.name,
            # A re-read is the single source of truth: the parsed config replaces
            # the inventory wholesale, so an empty result clears stale entries.
            vlans=vlans,
            ports=ports,
        )

    # -- writes --------------------------------------------------------------
    def push_config(self, device: Device) -> None:
        runner = self._runner(device)
        with runner:
            # JetStream has no UCI-style staging: every `configure` line mutates
            # running-config live, and `copy running-config startup-config` is the
            # only durable persist. So capture the current running-config first,
            # push the body without persisting, and only save once it applied
            # cleanly. On any failure, re-push the snapshot to restore the running
            # config and leave startup-config as the last-known-good (never saved).
            before = self._snapshot(runner, device)

            try:
                output = runner.run_shell(self._renderer.render_body(device))
            except Exception as exc:
                _RUNNER_LOG.warning(
                    "Push to %s failed mid-apply (%s); attempting to restore the "
                    "previous running-config.",
                    device.name,
                    exc,
                )
                self._restore(runner, before)
                raise

            error = _scan_for_errors(output)
            if error is not None:
                _RUNNER_LOG.warning(
                    "Push to %s was rejected by the switch (%s); restoring the "
                    "previous running-config.",
                    device.name,
                    error,
                )
                self._restore(runner, before)
                raise SshError(f"JetStream push rejected: {error}")

            # The whole batch applied cleanly; persist it to startup-config.
            runner.run_shell(["enable", self._renderer.SAVE_COMMAND])

    def _snapshot(self, runner: SshCommandRunner, device: Device) -> Device:
        """Read the current running-config so the push can be rolled back."""
        raw = runner.run_shell(["enable", "show running-config"])
        hostname, vlans, ports = self._parse_running_config(raw)
        return replace(device, name=hostname or device.name, vlans=vlans, ports=ports)

    def _restore(self, runner: SshCommandRunner, before: Device) -> None:
        """Best-effort re-push of the captured config; never raises.

        The renderer is additive (it re-asserts hostname/VLANs/ports but issues no
        deletes), so this restores known prior settings rather than guaranteeing a
        byte-perfect rollback. startup-config is deliberately left untouched, so a
        device reload always recovers the last-known-good config.
        """
        try:
            runner.run_shell(self._renderer.render_body(before))
        except Exception as exc:  # noqa: BLE001 - best-effort; original error wins
            _RUNNER_LOG.warning(
                "Could not restore the previous running-config on %s: %s",
                before.name,
                exc,
            )


    # -- parsing helpers -----------------------------------------------------
    @classmethod
    def _parse_running_config(
        cls, raw: str
    ) -> tuple[str, list[Vlan], list[SwitchPort]]:
        hostname = ""
        vlans: dict[int, Vlan] = {}
        ports: dict[int, SwitchPort] = {}
        current_vlan: int | None = None
        current_port: int | None = None

        for line in raw.splitlines():
            stripped = line.strip()
            if not stripped or stripped == "#":
                continue
            words = stripped.split()
            head = words[0].lower()

            if head == "hostname" and len(words) >= 2:
                hostname = cls._unquote(" ".join(words[1:]))
                current_vlan = current_port = None
            elif head == "vlan" and len(words) >= 2 and words[1].isdigit():
                current_vlan = int(words[1])
                current_port = None
                vlans.setdefault(
                    current_vlan, Vlan(vlan_id=current_vlan, name=f"VLAN{current_vlan}")
                )
            elif head == "name" and current_vlan is not None and len(words) >= 2:
                vlans[current_vlan] = Vlan(
                    vlan_id=current_vlan, name=cls._unquote(" ".join(words[1:]))
                )
            elif head == "interface" and len(words) >= 2:
                # `interface vlan N` is the management SVI, not a physical port.
                if words[1].lower() == "vlan":
                    current_vlan = current_port = None
                    continue
                num = words[-1].split("/")[-1]
                if num.isdigit():
                    current_port = int(num)
                    current_vlan = None
                    ports.setdefault(
                        current_port, SwitchPort(number=current_port, name=f"Gi1/0/{num}")
                    )
            elif head == "switchport" and current_port is not None:
                cls._apply_switchport(ports[current_port], words[1:])
            elif head == "shutdown" and current_port is not None:
                ports[current_port].enabled = False

        return (
            hostname,
            [vlans[v] for v in sorted(vlans)],
            [ports[p] for p in sorted(ports)],
        )

    @staticmethod
    def _unquote(value: str) -> str:
        """Strip a single pair of surrounding single/double quotes, if present."""
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            return value[1:-1]
        return value

    @staticmethod
    def _apply_switchport(port: SwitchPort, rest: list[str]) -> None:
        if not rest:
            return
        sub = rest[0].lower()
        if sub == "mode" and len(rest) >= 2:
            try:
                port.mode = PortMode(rest[1].lower())
            except ValueError:
                port.mode = PortMode.TRUNK
        elif sub == "access" and len(rest) >= 3 and rest[1].lower() == "vlan":
            port.mode = PortMode.ACCESS
            port.pvid = int(rest[2])
        elif sub == "general" and len(rest) >= 4 and rest[1].lower() == "allowed":
            vlan_ids = [int(v) for v in rest[3].split(",") if v.isdigit()]
            membership = rest[4].lower() if len(rest) >= 5 else ""
            if membership == "untagged":
                # An untagged member is an access assignment; the PVID is set by
                # the companion `switchport pvid` line.
                port.mode = PortMode.ACCESS
                if vlan_ids:
                    port.pvid = vlan_ids[0]
            else:
                # `... tagged` (or no keyword, as the mock emits) means trunk.
                port.mode = PortMode.TRUNK
                port.tagged_vlans = vlan_ids
        elif sub == "pvid" and len(rest) >= 2 and rest[1].isdigit():
            port.pvid = int(rest[1])
