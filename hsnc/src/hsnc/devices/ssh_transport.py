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
from collections import deque
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from ..entities import Device
from ..enums import DeviceKind

# Upper bound on the per-connection SSH transcript ring buffer (commands sent and
# device output). Older lines are dropped once the cap is reached. Overridable so
# operators can trade memory for a deeper history.
SSH_LOG_MAX_LINES = max(1, int(os.environ.get("HSNC_SSH_LOG_LINES", "5000") or "5000"))

# Platform defaults applied when a device's connection leaves a field blank.
_OPENWRT_DEFAULTS = {"port": 22, "username": "root", "password": "openwrt"}
_JETSTREAM_DEFAULTS = {"port": 22, "username": "admin", "password": "admin"}

# JetStream pager prompt shown for long output; answered with a space in _drain.
_PAGER_RE = re.compile(r"Press any key to continue|--More--", re.IGNORECASE)

# A returned CLI prompt ("hostname>", "hostname#", "hostname(config)#") sitting at
# the end of the buffer with no trailing newline. Used to know a command finished
# instead of guessing from an idle timeout, which races on slow switches.
_PROMPT_RE = re.compile(r"\S+[>#][ \t]*\Z")

# Dedicated logger for the optional SSH transcript mirror (see HSNC_SSH_TRANSCRIPT_
# DEBUG). It is pinned to DEBUG and stays independent of HSNC_LOG_LEVEL: lines are
# only emitted when a transcript is explicitly debug-enabled, so pinning is
# harmless when the feature is off, and enabled lines surface even when the rest of
# the app is logging at a higher threshold.
_TRANSCRIPT_LOG = logging.getLogger("hsnc.ssh.transcript")
_TRANSCRIPT_LOG.setLevel(logging.DEBUG)

# Per-device paramiko transport logs are re-pointed onto child channels named
# "paramiko.transport.<normalised-id>" so a single device can be debugged in
# isolation (see HSNC_DEVICE_<ID>_SSH_DEBUG).
_PARAMIKO_CHANNEL_PREFIX = "paramiko.transport."

# Paramiko's background transport thread logs unactionable tracebacks at ERROR when
# a device is unreachable or drops the connection (e.g. "Error reading SSH protocol
# banner", auth failures). We normalise every connection fault into a clean
# :class:`SshError` and already surface a readable WARNING ourselves, so by default
# we silence paramiko's own logger. The global HSNC_SSH_DEBUG flag raises it back to
# DEBUG (see :func:`apply_paramiko_global_debug`), which is also what captures the
# connection handshake; per-device debugging instead uses the child channels above.
logging.getLogger("paramiko").setLevel(logging.CRITICAL)


def apply_paramiko_global_debug(enabled: bool) -> None:
    """Set the base ``paramiko`` logger level from the global debug flag.

    When ``enabled`` (global ``HSNC_SSH_DEBUG``), paramiko logs at ``DEBUG`` —
    including the connection handshake and every device's transport activity.
    When disabled it is silenced at ``CRITICAL``; per-device debugging then relies
    on the post-handshake child channels and does not capture the handshake.
    """
    logging.getLogger("paramiko").setLevel(logging.DEBUG if enabled else logging.CRITICAL)


def _env_flag(value: str | None) -> bool:
    """Parse a boolean-ish env value. Truthy: ``1``, ``true``, ``yes``, ``on``."""
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class TranscriptEntry:
    """One recorded line of SSH activity.

    ``kind`` is ``sent`` (a command we issued), ``recv`` (output the device
    transmitted back), ``info`` (a connection lifecycle note) or ``error``.
    """

    ts: float
    kind: str
    text: str


class SshTranscript:
    """Thread-safe, bounded ring buffer of recent SSH activity for one runner.

    Output is split into individual lines so the frontend can render a terminal
    view; the buffer keeps at most ``maxlen`` lines (oldest dropped first). When
    ``debug`` is set, every recorded line is also mirrored to the
    ``hsnc.ssh.transcript`` logger at DEBUG, tagged with ``label``.
    """

    def __init__(
        self, maxlen: int = SSH_LOG_MAX_LINES, *, debug: bool = False, label: str = ""
    ) -> None:
        self._entries: deque[TranscriptEntry] = deque(maxlen=maxlen)
        self._lock = threading.Lock()
        self._debug = debug
        self._label = label

    def record(self, kind: str, text: str) -> None:
        if not text:
            return
        now = time.time()
        with self._lock:
            for line in text.splitlines():
                self._entries.append(TranscriptEntry(now, kind, line))
                if self._debug:
                    _TRANSCRIPT_LOG.debug("[%s] %s | %s", self._label, kind, line)

    def lines(self, limit: int | None = None) -> list[TranscriptEntry]:
        with self._lock:
            entries = list(self._entries)
        if limit is not None and 0 <= limit < len(entries):
            entries = entries[-limit:]
        return entries


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
    # Debug toggles resolved per device (see HSNC_SSH_TRANSCRIPT_DEBUG /
    # HSNC_SSH_DEBUG and their per-device variants). ``label`` identifies the
    # device in transcript log lines and the per-device paramiko channel.
    debug_transcript: bool = False
    debug_paramiko: bool = False
    label: str = ""


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
        self._transcript = SshTranscript(
            debug=target.debug_transcript, label=target.label or target.host
        )

    @property
    def transcript(self) -> SshTranscript:
        """The rolling record of commands sent and output received."""
        return self._transcript

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
            self._transcript.record(
                "error",
                f"SSH connection to {self._target.host}:{self._target.port} failed: {exc}",
            )
            raise SshError(
                f"SSH connection to {self._target.host}:{self._target.port} failed: {exc}"
            ) from exc
        self._transcript.record(
            "info",
            f"connected to {self._target.host}:{self._target.port} "
            f"as {self._target.username}",
        )
        self._apply_paramiko_channel(client)
        self._client = client
        return client

    def _apply_paramiko_channel(self, client) -> None:
        """Route this device's transport logs onto its own paramiko channel.

        Applied after the handshake (the high-level ``connect`` performs it
        internally), so the channel captures post-handshake activity — channel
        opens, command exec, keepalives and disconnects. When the device opted in
        via ``HSNC_DEVICE_<ID>_SSH_DEBUG`` the channel is raised to DEBUG; handshake
        logs are only captured separately by the global ``HSNC_SSH_DEBUG`` flag.
        """
        transport = client.get_transport()
        if transport is None:
            return
        channel = _PARAMIKO_CHANNEL_PREFIX + _normalise_id(
            self._target.label or self._target.host
        )
        transport.set_log_channel(channel)
        if self._target.debug_paramiko:
            logging.getLogger(channel).setLevel(logging.DEBUG)

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
        self._transcript.record("sent", command)
        _stdin, stdout, stderr = client.exec_command(command, timeout=self._target.timeout)
        out = stdout.read().decode("utf-8", "replace")
        err = stderr.read().decode("utf-8", "replace")
        status = stdout.channel.recv_exit_status()
        if out:
            self._transcript.record("recv", out)
        if err:
            self._transcript.record("recv", err)
        if status != 0:
            self._transcript.record("error", f"command exited with status {status}")
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
        banner = self._drain(channel)
        collected.append(banner)
        self._transcript.record("recv", banner)
        for command in commands:
            # CR-LF: real JetStream switches submit a CLI line on the carriage
            # return; the LF gives line-oriented readers (the mock) a boundary.
            channel.sendall(command.rstrip("\r\n") + "\r\n")
            self._transcript.record("sent", command)
            chunk = self._drain(channel)
            collected.append(chunk)
            self._transcript.record("recv", chunk)
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
        self._transcript = SshTranscript()

    @property
    def transcript(self) -> SshTranscript:
        return self._transcript

    def run(self, command: str) -> str:
        self.commands.append(command)
        self._transcript.record("sent", command)
        if any(command.startswith(prefix) for prefix in self._errors):
            self._transcript.record("error", f"command {command!r} failed (fake)")
            raise SshError(f"command {command!r} failed (fake)")
        if command in self._responses:
            self._transcript.record("recv", self._responses[command])
            return self._responses[command]
        best = ""
        for key in self._responses:
            if command.startswith(key) and len(key) > len(best):
                best = key
        result = self._responses.get(best, "")
        self._transcript.record("recv", result)
        return result

    def run_shell(self, commands: Sequence[str]) -> str:
        self.shell_invocations.append(list(commands))
        for command in commands:
            self._transcript.record("sent", command)
        self._transcript.record("recv", self._shell_output)
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

    def peek(self, target: SshTarget) -> PersistentSshRunner | None:
        """Return the existing runner for a target, or None if not yet created.

        Unlike :meth:`get`, this never creates a connection, so callers that only
        want to read an existing transcript don't spin up an empty runner.
        """
        with self._lock:
            return self._runners.get(self._key(target))

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
    # Optional SSH debugging, resolved per device (per-device value overrides the
    # global default in either direction).
    transcript_debug: bool = False
    paramiko_debug: bool = False
    device_transcript_debug: dict[str, bool] = None  # type: ignore[assignment]
    device_paramiko_debug: dict[str, bool] = None  # type: ignore[assignment]

    @staticmethod
    def from_env(environ: dict[str, str] | None = None) -> SshConnectionSettings:
        env = environ if environ is not None else os.environ
        device_passwords = {
            _device_id_from_env_key(key): value
            for key, value in env.items()
            if key.startswith("HSNC_DEVICE_") and key.endswith("_PASSWORD")
        }
        # Order matters: match the longer "_SSH_TRANSCRIPT_DEBUG" suffix first so a
        # transcript key is never misread as a paramiko ("_SSH_DEBUG") key.
        device_transcript_debug = _device_flags(env, "_SSH_TRANSCRIPT_DEBUG")
        device_paramiko_debug = _device_flags(env, "_SSH_DEBUG", "_SSH_TRANSCRIPT_DEBUG")
        accept = env.get("HSNC_SSH_ACCEPT_UNKNOWN_HOSTS", "1") not in ("0", "false", "False")
        return SshConnectionSettings(
            host_override=env.get("HSNC_SSH_HOST_OVERRIDE", ""),
            accept_unknown_hosts=accept,
            openwrt_password=env.get("HSNC_OPENWRT_SSH_PASSWORD", ""),
            jetstream_password=env.get("HSNC_JETSTREAM_SSH_PASSWORD", ""),
            device_passwords=device_passwords,
            transcript_debug=_env_flag(env.get("HSNC_SSH_TRANSCRIPT_DEBUG")),
            paramiko_debug=_env_flag(env.get("HSNC_SSH_DEBUG")),
            device_transcript_debug=device_transcript_debug,
            device_paramiko_debug=device_paramiko_debug,
        )


def _device_id_from_env_key(key: str) -> str:
    """``HSNC_DEVICE_SWITCH_1_PASSWORD`` -> normalised id token ``SWITCH_1``."""
    return key[len("HSNC_DEVICE_"):-len("_PASSWORD")]


def _device_flags(
    env: dict[str, str], suffix: str, *exclude_suffixes: str
) -> dict[str, bool]:
    """Collect ``HSNC_DEVICE_<ID>{suffix}`` boolean overrides keyed by id token.

    ``exclude_suffixes`` lets a shorter suffix skip keys that actually belong to a
    longer one (e.g. ``_SSH_DEBUG`` excludes ``_SSH_TRANSCRIPT_DEBUG``).
    """
    flags: dict[str, bool] = {}
    for key, value in env.items():
        if not (key.startswith("HSNC_DEVICE_") and key.endswith(suffix)):
            continue
        if any(key.endswith(other) for other in exclude_suffixes):
            continue
        device_id = key[len("HSNC_DEVICE_"):-len(suffix)]
        flags[device_id] = _env_flag(value)
    return flags


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
        # The global paramiko flag drives the base logger level, which is also what
        # captures the connection handshake. Apply it as soon as a resolver exists.
        apply_paramiko_global_debug(self._settings.paramiko_debug)

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
            debug_transcript=self._flag_for(
                device, self._settings.device_transcript_debug, self._settings.transcript_debug
            ),
            debug_paramiko=self._flag_for(
                device, self._settings.device_paramiko_debug, self._settings.paramiko_debug
            ),
            label=device.id,
        )

    def _flag_for(
        self, device: Device, device_flags: dict[str, bool] | None, global_default: bool
    ) -> bool:
        """Per-device flag, falling back to the global default.

        An explicit per-device entry wins in either direction (it can force the
        flag off even when the global default is on).
        """
        flags = device_flags or {}
        specific = flags.get(_normalise_id(device.id))
        if specific is not None:
            return specific
        return global_default

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
