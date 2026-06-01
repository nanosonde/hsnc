"""Use case: build the dashboard summary."""

from __future__ import annotations

from ...domain.enums import DeviceKind, DeviceStatus
from ...domain.interfaces import ConfigRepository, RuntimeStore
from ..dtos import (
    AssociationFailureRow,
    DashboardSummary,
    StatItem,
)
from ..services import NetworkStateService


class GetDashboardSummary:
    """Aggregate site-wide counters and recent failures for the dashboard."""

    def __init__(
        self,
        config: ConfigRepository,
        network: NetworkStateService,
        runtime: RuntimeStore,
    ) -> None:
        self._config = config
        self._network = network
        self._runtime = runtime

    def execute(self) -> DashboardSummary:
        site = self._config.get_site()
        devices = self._network.devices()
        clients = self._network.clients()

        switches = [d for d in devices if d.kind is DeviceKind.SWITCH]
        aps = [d for d in devices if d.kind is DeviceKind.ACCESS_POINT]
        gateways = [d for d in devices if d.kind is DeviceKind.GATEWAY]

        gateway_status = "N/A"
        if gateways:
            gateway_status = (
                "Online" if gateways[0].status is DeviceStatus.CONNECTED else "Offline"
            )

        guests = [c for c in clients if c.network.lower() == "guest"]

        stats = [
            StatItem("Internet Capacity", "N/A"),
            StatItem("Gateway", gateway_status),
            StatItem("Switches", str(len(switches))),
            StatItem("EAPs", str(len(aps))),
            StatItem("Clients", str(len(clients))),
            StatItem("Guests", str(len(guests))),
        ]

        failures = self._runtime.latest_association_failures()
        failure_rows = [AssociationFailureRow(f.category, f.count) for f in failures]
        failure_total = sum(f.count for f in failures)

        admins = len(self._config.list_users())

        return DashboardSummary(
            site_name=site.name,
            stats=stats,
            admin_count=admins,
            device_count=len(devices),
            alert_count=failure_total,
            cloud_status="Connected",
            association_failures=failure_rows,
            association_failure_total=failure_total,
        )
