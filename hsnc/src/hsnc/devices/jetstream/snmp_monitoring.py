"""JetStream runtime monitoring over SNMPv3.

The monitoring plane never uses SSH: JetStream switches are polled via SNMPv3
(USM, ``authPriv`` by default). The JetStream platform always uses this provider
for live runtime data (the SSH CLI is reserved for the configuration plane).

Only the non-secret target (host/port) lives in ``devices.yaml`` (and may be
omitted to derive it from the device IP); the SNMPv3 user and auth/priv keys come
from the environment (``HSNC_SNMP_*`` globals and per-device
``HSNC_DEVICE_<ID>_SNMP_*`` overrides).

``pysnmp`` is an optional dependency (the ``snmp`` extra) and is imported lazily,
so the rest of the application — and the unit tests, which inject a fake
:class:`SnmpClient` — run without it installed. Modern ``pysnmp`` (6/7) ships only
the asyncio hlapi, so the synchronous :class:`SnmpClient` methods drive it via
:func:`asyncio.run`.
"""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Protocol

from ...entities import Client, Device
from ...enums import ConnectionType, DeviceStatus
from ...interfaces import MonitoringProvider
from ...value_objects import MacAddress
from ..ssh_transport import _normalise_id

# Standard MIB-II / BRIDGE-MIB object identifiers.
_OID_SYS_DESCR = "1.3.6.1.2.1.1.1.0"
_OID_SYS_UPTIME = "1.3.6.1.2.1.1.3.0"  # TimeTicks, hundredths of a second
_OID_SYS_NAME = "1.3.6.1.2.1.1.5.0"
_OID_FDB_PORT = "1.3.6.1.2.1.17.4.3.1.2"  # dot1dTpFdbPort (walked)

_DEFAULT_PORT = 161


@dataclass(frozen=True)
class SnmpCredentials:
    """SNMPv3 USM credentials."""

    user: str = ""
    auth_key: str = ""
    priv_key: str = ""
    auth_proto: str = "SHA"  # SHA | MD5
    priv_proto: str = "AES"  # AES | DES
    level: str = "authPriv"  # authPriv | authNoPriv | noAuthNoPriv


@dataclass(frozen=True)
class SnmpTarget:
    """A resolved SNMP target for one device."""

    host: str
    port: int
    credentials: SnmpCredentials


class SnmpClient(Protocol):
    """Minimal SNMP read interface (for testability)."""

    def get(self, oids: list[str]) -> dict[str, str]:
        """Return a mapping of OID -> value for the requested scalar OIDs."""
        ...

    def walk(self, oid: str) -> list[tuple[str, str]]:
        """Return ``(oid, value)`` pairs for the subtree rooted at ``oid``."""
        ...


SnmpClientFactory = Callable[[SnmpTarget], SnmpClient]


@dataclass(frozen=True)
class SnmpConnectionSettings:
    """Environment-derived SNMPv3 settings (global defaults + per-device)."""

    credentials: SnmpCredentials = SnmpCredentials()
    port: int = _DEFAULT_PORT
    device_overrides: dict[str, dict[str, str]] | None = None

    @staticmethod
    def from_env(environ: dict[str, str] | None = None) -> SnmpConnectionSettings:
        env = environ if environ is not None else os.environ
        creds = SnmpCredentials(
            user=env.get("HSNC_SNMP_USER", ""),
            auth_key=env.get("HSNC_SNMP_AUTH_KEY", ""),
            priv_key=env.get("HSNC_SNMP_PRIV_KEY", ""),
            auth_proto=env.get("HSNC_SNMP_AUTH_PROTO", "SHA"),
            priv_proto=env.get("HSNC_SNMP_PRIV_PROTO", "AES"),
            level=env.get("HSNC_SNMP_LEVEL", "authPriv"),
        )
        try:
            port = int(env.get("HSNC_SNMP_PORT", _DEFAULT_PORT))
        except ValueError:
            port = _DEFAULT_PORT
        overrides: dict[str, dict[str, str]] = {}
        suffixes = {
            "_SNMP_USER": "user",
            "_SNMP_AUTH_KEY": "auth_key",
            "_SNMP_PRIV_KEY": "priv_key",
            "_SNMP_AUTH_PROTO": "auth_proto",
            "_SNMP_PRIV_PROTO": "priv_proto",
            "_SNMP_LEVEL": "level",
            "_SNMP_PORT": "port",
        }
        for key, value in env.items():
            if not key.startswith("HSNC_DEVICE_"):
                continue
            for suffix, field in suffixes.items():
                if key.endswith(suffix):
                    device_id = key[len("HSNC_DEVICE_"):-len(suffix)]
                    overrides.setdefault(device_id, {})[field] = value
                    break
        return SnmpConnectionSettings(
            credentials=creds, port=port, device_overrides=overrides or None
        )

    def resolve(self, device: Device) -> SnmpTarget:
        target = device.monitoring.target if device.monitoring else None
        host = (target.endpoint if target and target.endpoint else "").strip()
        port = target.port if target and target.port else self.port
        if host and ":" in host and "[" not in host:
            host, _, raw_port = host.rpartition(":")
            if raw_port.isdigit() and not (target and target.port):
                port = int(raw_port)
        if not host:
            if device.ip is None:
                raise ValueError(
                    f"device {device.id!r} has no SNMP endpoint or IP to derive one"
                )
            host = str(device.ip)
        overrides = (self.device_overrides or {}).get(_normalise_id(device.id), {})
        creds = self.credentials
        if overrides:
            creds = replace(
                creds,
                **{k: v for k, v in overrides.items() if k != "port" and hasattr(creds, k)},
            )
            if "port" in overrides and overrides["port"].isdigit():
                port = int(overrides["port"])
        return SnmpTarget(host=host, port=port or _DEFAULT_PORT, credentials=creds)


def _default_client_factory(target: SnmpTarget) -> SnmpClient:
    return _PysnmpClient(target)


class JetStreamSnmpMonitoringProvider(MonitoringProvider):
    """Reads JetStream runtime state over SNMPv3."""

    def __init__(
        self,
        settings: SnmpConnectionSettings | None = None,
        client_factory: SnmpClientFactory = _default_client_factory,
    ) -> None:
        self._settings = settings or SnmpConnectionSettings.from_env()
        self._client_factory = client_factory

    def _client(self, device: Device) -> SnmpClient:
        return self._client_factory(self._settings.resolve(device))

    def fetch_status(self, device: Device) -> Device:
        client = self._client(device)
        values = client.get([_OID_SYS_DESCR, _OID_SYS_UPTIME, _OID_SYS_NAME])
        uptime_ticks = _to_int(values.get(_OID_SYS_UPTIME))
        return replace(
            device,
            status=DeviceStatus.CONNECTED,
            name=values.get(_OID_SYS_NAME) or device.name,
            model=values.get(_OID_SYS_DESCR) or device.model,
            uptime_seconds=uptime_ticks // 100,
        )

    def fetch_clients(self, device: Device) -> list[Client]:
        client = self._client(device)
        clients: list[Client] = []
        for oid, port in client.walk(_OID_FDB_PORT):
            mac = _mac_from_fdb_oid(oid)
            if mac is None:
                continue
            clients.append(
                Client(
                    id=f"{device.id}-{mac}",
                    name=str(mac),
                    mac=mac,
                    connection=ConnectionType.WIRED,
                    status=DeviceStatus.CONNECTED,
                    ap_or_port=f"Port {port}",
                    site_id=device.site_id,
                )
            )
        return clients


def _to_int(value: str | None) -> int:
    if not value:
        return 0
    try:
        return int(value)
    except ValueError:
        return 0


def _mac_from_fdb_oid(oid: str) -> MacAddress | None:
    """Extract the MAC from the trailing six octets of a dot1dTpFdb OID."""
    parts = oid.strip(".").split(".")
    if len(parts) < 6:
        return None
    try:
        octets = [int(part) for part in parts[-6:]]
    except ValueError:
        return None
    if any(octet < 0 or octet > 255 for octet in octets):
        return None
    try:
        return MacAddress(":".join(f"{octet:02X}" for octet in octets))
    except ValueError:
        return None


class _PysnmpClient:
    """Default :class:`SnmpClient` backed by ``pysnmp`` (lazy import).

    ``pysnmp`` 6/7 expose only the asyncio hlapi, so the synchronous
    :class:`SnmpClient` methods build a coroutine and run it with
    :func:`asyncio.run`.
    """

    def __init__(self, target: SnmpTarget) -> None:
        self._target = target

    def _usm(self):  # pragma: no cover - requires pysnmp + network
        from pysnmp.hlapi.v3arch.asyncio import (
            UsmUserData,
            usmAesCfb128Protocol,
            usmDESPrivProtocol,
            usmHMACMD5AuthProtocol,
            usmHMACSHAAuthProtocol,
            usmNoPrivProtocol,
        )

        creds = self._target.credentials
        auth_protos = {"SHA": usmHMACSHAAuthProtocol, "MD5": usmHMACMD5AuthProtocol}
        priv_protos = {"AES": usmAesCfb128Protocol, "DES": usmDESPrivProtocol}
        level = creds.level.lower()
        if level == "noauthnopriv":
            return UsmUserData(creds.user)
        if level == "authnopriv":
            return UsmUserData(
                creds.user,
                authKey=creds.auth_key,
                authProtocol=auth_protos.get(creds.auth_proto.upper(), usmHMACSHAAuthProtocol),
                privProtocol=usmNoPrivProtocol,
            )
        return UsmUserData(
            creds.user,
            authKey=creds.auth_key,
            privKey=creds.priv_key,
            authProtocol=auth_protos.get(creds.auth_proto.upper(), usmHMACSHAAuthProtocol),
            privProtocol=priv_protos.get(creds.priv_proto.upper(), usmAesCfb128Protocol),
        )

    def get(self, oids: list[str]) -> dict[str, str]:  # pragma: no cover - needs network
        return asyncio.run(self._get_async(oids))

    async def _get_async(  # pragma: no cover - needs network
        self, oids: list[str]
    ) -> dict[str, str]:
        from pysnmp.hlapi.v3arch.asyncio import (
            ContextData,
            ObjectIdentity,
            ObjectType,
            SnmpEngine,
            UdpTransportTarget,
            get_cmd,
        )

        engine = SnmpEngine()
        result: dict[str, str] = {}
        try:
            transport = await UdpTransportTarget.create(
                (self._target.host, self._target.port)
            )
            usm = self._usm()
            context = ContextData()
            for oid in oids:
                error_indication, error_status, _idx, var_binds = await get_cmd(
                    engine,
                    usm,
                    transport,
                    context,
                    ObjectType(ObjectIdentity(oid)),
                )
                if error_indication or error_status:
                    continue
                for name, value in var_binds:
                    result[str(name)] = value.prettyPrint()
        finally:
            engine.close_dispatcher()
        return result

    def walk(self, oid: str) -> list[tuple[str, str]]:  # pragma: no cover - needs network
        return asyncio.run(self._walk_async(oid))

    async def _walk_async(  # pragma: no cover - needs network
        self, oid: str
    ) -> list[tuple[str, str]]:
        from pysnmp.hlapi.v3arch.asyncio import (
            ContextData,
            ObjectIdentity,
            ObjectType,
            SnmpEngine,
            UdpTransportTarget,
            walk_cmd,
        )

        engine = SnmpEngine()
        pairs: list[tuple[str, str]] = []
        try:
            transport = await UdpTransportTarget.create(
                (self._target.host, self._target.port)
            )
            usm = self._usm()
            context = ContextData()
            async for error_indication, error_status, _idx, var_binds in walk_cmd(
                engine,
                usm,
                transport,
                context,
                ObjectType(ObjectIdentity(oid)),
                lexicographicMode=False,
            ):
                if error_indication or error_status:
                    break
                for name, value in var_binds:
                    pairs.append((str(name), value.prettyPrint()))
        finally:
            engine.close_dispatcher()
        return pairs
