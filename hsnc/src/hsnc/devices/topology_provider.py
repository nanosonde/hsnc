"""A simple topology provider mirroring the reference layout.

Builds: Internet -> Gateway -> Switch -> {Access Points, Client Group}. When a
gateway is absent the switch attaches directly to the Internet node, matching
the reference screenshot.
"""

from __future__ import annotations

from ..entities import (
    Client,
    Device,
    Topology,
    TopologyLink,
    TopologyNode,
)
from ..enums import DeviceKind
from ..interfaces import TopologyProvider

_INTERNET_ID = "internet"
_CLIENT_GROUP_ID = "client-group"


class SimpleTopologyProvider(TopologyProvider):
    """Derives a small hub-and-spoke topology from devices and clients."""

    def build(self, devices: list[Device], clients: list[Client]) -> Topology:
        nodes: list[TopologyNode] = [
            TopologyNode(id=_INTERNET_ID, label="Internet", kind="internet")
        ]
        links: list[TopologyLink] = []

        gateways = [d for d in devices if d.kind is DeviceKind.GATEWAY]
        switches = [d for d in devices if d.kind is DeviceKind.SWITCH]
        aps = [d for d in devices if d.kind is DeviceKind.ACCESS_POINT]

        upstream_id = _INTERNET_ID
        for gateway in gateways:
            nodes.append(
                TopologyNode(id=gateway.id, label=gateway.name, kind="device")
            )
            links.append(TopologyLink(upstream_id, gateway.id))
            upstream_id = gateway.id

        for switch in switches:
            badge = len(clients) if clients else None
            nodes.append(
                TopologyNode(id=switch.id, label=switch.name, kind="device", badge=badge)
            )
            links.append(TopologyLink(upstream_id, switch.id))

            for ap in aps:
                nodes.append(
                    TopologyNode(id=ap.id, label=ap.name, kind="device")
                )
                links.append(TopologyLink(switch.id, ap.id))

            if clients:
                nodes.append(
                    TopologyNode(
                        id=_CLIENT_GROUP_ID,
                        label="Client Group",
                        kind="client_group",
                        badge=len(clients),
                    )
                )
                links.append(TopologyLink(switch.id, _CLIENT_GROUP_ID))

        return Topology(nodes=nodes, links=links)
