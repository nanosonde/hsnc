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

import logging
import os
import re
import threading
import time
from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ..entities import Device
from ..enums import DeviceKind

# Platform defaults applied when a device's connection leaves a field blank.
_OPENWRT_DEFAULTS = {"port": 22, "username": "root", "password": "openwrt"}
_JETSTREAM_DEFAULTS = {"port": 22, "username": "admin", "password": "admin"}

# JetStream pager prompt shown for long output; answered with a space in _drain.
_PAGER_RE = re.compile(r"Press any key to continue|--More--", re.IGNORECASE)

# A returned CLI prompt ("hostname>", "hostname#", "hostname(config)#") sitting at
# the end of the buffer with no trailing newline. Used to know a command finished
# instead of guessing from an idle timeout, which races on slow switches.
_PROMPT_RE = re.compile(r"\S+[>#][ \t]*\Z")

# Paramiko's background transport thread logs unactionable tracebacks at ERROR
# when a device is unreachable or drops the connection (e.g. "Error reading SSH
# protocol banner", auth failures). We normalise every connection fault into a
# clean :class:`SshError` and already surface a readable WARNING ourselves, so we
# raise the threshold to keep that internal chatter out of the application log.
# Set HSNC_SSH_DEBUG=1 to restore paramiko's own logging while diagnosing.
if not os.environ.get("HSNC_SSH_DEBUG"):
    logging.getLogger("paramiko").setLevel(logging.CRITICAL)


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
            transport = self._client.get_transport()
            if transport is not None and transport.is_active():
                return self._client
            # The peer dropped a previously-open connection (common on switches
            # that close idle sessions); discard it and reconnect below.
            self.close()
        try:
            import paramiko  # noqa: PLC0415 - lazy: only needed for real SSH
        except ImportError as exc:  # pragma: no cover - depends on environment
            raise SshError(
                "paramiko is required for real device SSH access. "
                "Install it with: pip install 'hsnc[ssh]'"
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
            # CR-LF: real JetStream switches submit a CLI line on the carriage
            # return; the LF gives line-oriented readers (the mock) a boundary.
            channel.sendall(command.rstrip("\r\n") + "\r\n")
            collected.append(self._drain(channel))
        channel.close()
        return "".join(collected)

    @staticmethod
    def _drain(channel, idle: float = 1.0, limit: float = 20.0) -> str:
        """Read a shell channel until the CLI prompt returns (or it goes quiet).

        Stopping on the returned prompt rather than a fixed idle window keeps
        commands from being sent before a slow switch has finished the previous
        one. JetStream switches page long output with a "Press any key to
        continue" prompt; we answer it with a space so multi-page reads complete.
        """
        chunks: list[str] = []
        buf = ""
        deadline = time.monotonic() + limit
        last = time.monotonic()
        while time.monotonic() < deadline:
            if channel.recv_ready():
                chunk = channel.recv(65536).decode("utf-8", "replace")
                chunks.append(chunk)
                buf += chunk
                if _PAGER_RE.search(chunk):
                    channel.sendall(" ")
                elif _PROMPT_RE.search(buf):
                    break
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


class PersistentSshRunner(ParamikoSshRunner):
    """Long-lived, thread-safe SSH runner for a pooled device connection.

    Unlike :class:`ParamikoSshRunner` (which connects per use and closes on
    ``__exit__``), this keeps a single SSH connection open across calls and
    transparently reconnects after a dropped connection. A lock serialises
    access so the pool's keepalive thread and on-demand command calls never
    use the channel concurrently.

    The context-manager protocol is a no-op on exit so adapters written as
    ``with runner: ...`` reuse the persistent connection instead of closing it.
    """

    def __init__(self, target: SshTarget) -> None:
        super().__init__(target)
        self._op_lock = threading.RLock()

    def __enter__(self) -> PersistentSshRunner:
        return self

    def __exit__(self, *exc_info: object) -> None:
        # Keep the connection open; the pool owns its lifecycle.
        return None

    def ensure_connected(self) -> None:
        """Open the connection if needed; raises :class:`SshError` on failure."""
        with self._op_lock:
            self._connect()

    def is_alive(self) -> bool:
        with self._op_lock:
            client = self._client
            if client is None:
                return False
            transport = client.get_transport()
            return bool(transport and transport.is_active())

    def keepalive(self) -> bool:
        """Best-effort liveness probe; returns True if the connection is healthy."""
        with self._op_lock:
            try:
                self._connect()
                transport = self._client.get_transport() if self._client else None
                if transport is None or not transport.is_active():
                    raise SshError("transport not active")
                transport.send_ignore()
                return True
            except Exception:  # noqa: BLE001 - liveness probe never raises
                self.close()
                return False

    def run(self, command: str) -> str:
        with self._op_lock:
            try:
                return super().run(command)
            except Exception:  # noqa: BLE001 - dropped link: reconnect once, retry
                self.close()
                return super().run(command)

    def run_shell(self, commands: Sequence[str]) -> str:
        with self._op_lock:
            try:
                return super().run_shell(commands)
            except Exception:  # noqa: BLE001 - dropped link: reconnect once, retry
                self.close()
                return super().run_shell(commands)


class PersistentRunnerRegistry:
    """Caches one :class:`PersistentSshRunner` per resolved target.

    Used as a :data:`RunnerFactory` so device adapters transparently reuse the
    pool's warm connections. Keyed by the connection tuple so repeated
    resolutions of the same device share a single connection.
    """

    def __init__(self) -> None:
        self._runners: dict[tuple[str, int, str], PersistentSshRunner] = {}
        self._lock = threading.Lock()

    @staticmethod
    def _key(target: SshTarget) -> tuple[str, int, str]:
        return (target.host, target.port, target.username)

    def get(self, target: SshTarget) -> PersistentSshRunner:
        with self._lock:
            key = self._key(target)
            runner = self._runners.get(key)
            if runner is None:
                runner = PersistentSshRunner(target)
                self._runners[key] = runner
            return runner

    def all_runners(self) -> list[PersistentSshRunner]:
        with self._lock:
            return list(self._runners.values())

    def close_all(self) -> None:
        with self._lock:
            for runner in self._runners.values():
                runner.close()
            self._runners.clear()


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
            if key.startswith("HSNC_DEVICE_") and key.endswith("_PASSWORD")
        }
        accept = env.get("HSNC_SSH_ACCEPT_UNKNOWN_HOSTS", "1") not in ("0", "false", "False")
        return SshConnectionSettings(
            host_override=env.get("HSNC_SSH_HOST_OVERRIDE", ""),
            accept_unknown_hosts=accept,
            openwrt_password=env.get("HSNC_OPENWRT_SSH_PASSWORD", ""),
            jetstream_password=env.get("HSNC_JETSTREAM_SSH_PASSWORD", ""),
            device_passwords=device_passwords,
        )


def _device_id_from_env_key(key: str) -> str:
    """``HSNC_DEVICE_SWITCH_1_PASSWORD`` -> normalised id token ``SWITCH_1``."""
    return key[len("HSNC_DEVICE_"):-len("_PASSWORD")]


def _normalise_id(device_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "_", device_id).upper()


class SshConnectionResolver:
    """Resolves a :class:`Device` into an :class:`SshTarget`.

    Host/port/username come from the device's :class:`DeviceConnection` (falling
    back to the management IP and platform defaults). The password is resolved
    only from the environment, in order of precedence:

    1. ``HSNC_DEVICE_<ID>_PASSWORD`` (id upper-cased, non-alphanumerics -> ``_``)
    2. ``HSNC_{OPENWRT,JETSTREAM}_SSH_PASSWORD`` (per platform)
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
