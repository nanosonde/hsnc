"""SSH transport for the real device adapters.

Provides a small seam between the OpenWrt/JetStream adapters and the underlying
SSH library so adapters stay unit-testable:

* :class:`SshTarget` — resolved connection details (host/port/user/password).
* :class:`SshCommandRunner` — the abstract transport the adapters depend on.
* :class:`ParamikoSshRunner` — the real implementation (``paramiko`` imported
  lazily so the optional ``[ssh]`` extra is only needed for real-device mode).
* :class:`SshConnectionResolver` — turns a :class:`Device` plus environment into
  an :class:`SshTarget`, keeping passwords out of the declarative inventory.

OpenWrt uses :meth:`SshCommandRunner.run` (one ``exec`` per stateless ``uci`` /
``ubus`` command). JetStream uses :meth:`SshCommandRunner.run_shell` (a single
interactive session, because its CLI config mode is stateful).
"""

from __future__ import annotations

import os
import re
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ...domain.entities import Device
from ...domain.enums import DeviceKind

# Platform defaults applied when a device's connection leaves a field blank.
_OPENWRT_DEFAULTS = {"port": 22, "username": "root", "password": "openwrt"}
_JETSTREAM_DEFAULTS = {"port": 22, "username": "admin", "password": "admin"}


class SshError(RuntimeError):
    """Raised when an SSH connection or command fails."""


@dataclass(frozen=True)
class SshTarget:
    """Fully resolved SSH connection details for a single device."""

    host: str
    port: int
    username: str
    password: str
    accept_unknown_hosts: bool = True
    timeout: float = 10.0


class SshCommandRunner(ABC):
    """Abstract SSH transport the device adapters depend on."""

    @abstractmethod
    def run(self, command: str) -> str:
        """Run a single command and return its combined stdout."""

    def run_all(self, commands: Sequence[str]) -> str:
        """Run several commands in order, returning their concatenated output."""
        return "".join(self.run(cmd) for cmd in commands)

    @abstractmethod
    def run_shell(self, commands: Sequence[str]) -> str:
        """Run commands in one interactive shell session (for stateful CLIs)."""


class ParamikoSshRunner(SshCommandRunner):
    """Real SSH transport backed by ``paramiko`` (lazily imported)."""

    def __init__(self, target: SshTarget) -> None:
        self._target = target
        self._client = None  # lazily connected paramiko.SSHClient

    # -- connection lifecycle ------------------------------------------------
    def _connect(self):
        if self._client is not None:
            return self._client
        try:
            import paramiko  # noqa: PLC0415 - lazy: only needed for real SSH
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise SshError(
                "paramiko is required for real device SSH access. "
                "Install it with: pip install 'sdn-manager[ssh]'"
            ) from exc

        client = paramiko.SSHClient()
        client.load_system_host_keys()
        if self._target.accept_unknown_hosts:
            client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        else:
            client.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            client.connect(
                self._target.host,
                port=self._target.port,
                username=self._target.username,
                password=self._target.password,
                look_for_keys=False,
                allow_agent=False,
                timeout=self._target.timeout,
            )
        except Exception as exc:  # noqa: BLE001 - normalise to SshError
            raise SshError(
                f"SSH connection to {self._target.host}:{self._target.port} failed: {exc}"
            ) from exc
        self._client = client
        return client

    def close(self) -> None:
        if self._client is not None:
            self._client.close()
            self._client = None

    def __enter__(self) -> ParamikoSshRunner:
        self._connect()
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # -- command execution ---------------------------------------------------
    def run(self, command: str) -> str:
        client = self._connect()
        _stdin, stdout, stderr = client.exec_command(command, timeout=self._target.timeout)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        status = stdout.channel.recv_exit_status()
        if status != 0:
            raise SshError(
                f"command {command!r} exited with status {status}: {err.strip() or out.strip()}"
            )
        return out

    def run_shell(self, commands: Sequence[str]) -> str:
        client = self._connect()
        channel = client.invoke_shell()
        channel.settimeout(self._target.timeout)
        collected: list[str] = []
        # Drain the initial banner/prompt.
        collected.append(self._drain(channel))
        for command in commands:
            channel.sendall(command.rstrip("\n") + "\n")
            collected.append(self._drain(channel))
        channel.close()
        return "".join(collected)

    @staticmethod
    def _drain(channel, idle: float = 0.4, limit: float = 10.0) -> str:
        """Read from a shell channel until it stays quiet for ``idle`` seconds."""
        chunks: list[str] = []
        deadline = time.monotonic() + limit
        last = time.monotonic()
        while time.monotonic() < deadline:
            if channel.recv_ready():
                chunks.append(channel.recv(65536).decode("utf-8", "replace"))
                last = time.monotonic()
            elif time.monotonic() - last >= idle:
                break
            else:
                time.sleep(0.05)
        return "".join(chunks)


class FakeSshRunner(SshCommandRunner):
    """In-memory :class:`SshCommandRunner` for unit tests.

    ``responses`` maps a command (matched exactly first, then by longest prefix)
    to canned stdout. Commands whose prefix is listed in ``errors`` raise
    :class:`SshError`, so tests can exercise fallback paths. Executed commands and
    interactive shell invocations are recorded so tests can assert on the
    commands an adapter sends.
    """

    def __init__(
        self,
        responses: dict[str, str] | None = None,
        shell_output: str = "",
        errors: Sequence[str] | None = None,
    ) -> None:
        self._responses = responses or {}
        self._shell_output = shell_output
        self._errors = tuple(errors or ())
        self.commands: list[str] = []
        self.shell_invocations: list[list[str]] = []

    def run(self, command: str) -> str:
        self.commands.append(command)
        if any(command.startswith(prefix) for prefix in self._errors):
            raise SshError(f"command {command!r} failed (fake)")
        if command in self._responses:
            return self._responses[command]
        best = ""
        for key in self._responses:
            if command.startswith(key) and len(key) > len(best):
                best = key
        return self._responses.get(best, "")

    def run_shell(self, commands: Sequence[str]) -> str:
        self.shell_invocations.append(list(commands))
        return self._shell_output

    def __enter__(self) -> FakeSshRunner:
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def close(self) -> None:
        return None


#: A factory turning a resolved target into a runner (swapped for a fake in tests).
RunnerFactory = Callable[[SshTarget], SshCommandRunner]


def default_runner_factory(target: SshTarget) -> SshCommandRunner:
    """Default runner factory: a real paramiko-backed runner."""
    return ParamikoSshRunner(target)


@dataclass(frozen=True)
class SshConnectionSettings:
    """Environment-derived SSH defaults that complement per-device connection."""

    host_override: str = ""
    accept_unknown_hosts: bool = True
    openwrt_password: str = ""
    jetstream_password: str = ""
    device_passwords: dict[str, str] = None  # type: ignore[assignment]

    @staticmethod
    def from_env(environ: dict[str, str] | None = None) -> SshConnectionSettings:
        env = environ if environ is not None else os.environ
        device_passwords = {
            _device_id_from_env_key(key): value
            for key, value in env.items()
            if key.startswith("SDNMAN_DEVICE_") and key.endswith("_PASSWORD")
        }
        accept = env.get("SDNMAN_SSH_ACCEPT_UNKNOWN_HOSTS", "1") not in ("0", "false", "False")
        return SshConnectionSettings(
            host_override=env.get("SDNMAN_SSH_HOST_OVERRIDE", ""),
            accept_unknown_hosts=accept,
            openwrt_password=env.get("SDNMAN_OPENWRT_SSH_PASSWORD", ""),
            jetstream_password=env.get("SDNMAN_JETSTREAM_SSH_PASSWORD", ""),
            device_passwords=device_passwords,
        )


def _device_id_from_env_key(key: str) -> str:
    """``SDNMAN_DEVICE_SWITCH_1_PASSWORD`` -> normalised id token ``SWITCH_1``."""
    return key[len("SDNMAN_DEVICE_"):-len("_PASSWORD")]


def _normalise_id(device_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", device_id).upper()


class SshConnectionResolver:
    """Resolves a :class:`Device` into an :class:`SshTarget`.

    Host/port/username come from the device's :class:`DeviceConnection` (falling
    back to the management IP and platform defaults). The password is resolved
    only from the environment, in order of precedence:

    1. ``SDNMAN_DEVICE_<ID>_PASSWORD`` (id upper-cased, non-alphanumerics -> ``_``)
    2. ``SDNMAN_{OPENWRT,JETSTREAM}_SSH_PASSWORD`` (per platform)
    3. the platform default (``openwrt`` / ``admin``)
    """

    def __init__(self, settings: SshConnectionSettings | None = None) -> None:
        self._settings = settings or SshConnectionSettings.from_env()

    def resolve(self, device: Device) -> SshTarget:
        defaults = (
            _JETSTREAM_DEFAULTS
            if device.kind is DeviceKind.SWITCH and not _is_openwrt(device)
            else _OPENWRT_DEFAULTS
        )
        conn = device.connection
        host = self._settings.host_override or (conn.host if conn and conn.host else "")
        if not host:
            if device.ip is None:
                raise SshError(f"device {device.id!r} has no IP or connection host")
            host = str(device.ip)
        port = (conn.port if conn and conn.port else 0) or defaults["port"]
        username = (conn.username if conn and conn.username else "") or defaults["username"]
        return SshTarget(
            host=host,
            port=port,
            username=username,
            password=self._password_for(device, defaults["password"]),
            accept_unknown_hosts=self._settings.accept_unknown_hosts,
        )

    def _password_for(self, device: Device, platform_default: str) -> str:
        passwords = self._settings.device_passwords or {}
        specific = passwords.get(_normalise_id(device.id))
        if specific:
            return specific
        if device.kind is DeviceKind.SWITCH and not _is_openwrt(device):
            return self._settings.jetstream_password or platform_default
        return self._settings.openwrt_password or platform_default


def _is_openwrt(device: Device) -> bool:
    return "openwrt" in device.model.lower()
