"""Use case: build the network topology view."""

from __future__ import annotations

from ..dtos import TopologyLinkView, TopologyNodeView, TopologyView
from ..interfaces import TopologyProvider
from ..services import NetworkStateService


class GetTopology:
    """Assemble the topology graph for the site."""

    def __init__(self, network: NetworkStateService, provider: TopologyProvider) -> None:
        self._network = network
        self._provider = provider

    def execute(self) -> TopologyView:
        devices = self._network.devices()
        clients = self._network.clients()
        topology = self._provider.build(devices, clients)
        return TopologyView(
            nodes=[
                TopologyNodeView(n.id, n.label, n.kind, n.badge) for n in topology.nodes
            ],
            links=[TopologyLinkView(link.source_id, link.target_id) for link in topology.links],
        )
