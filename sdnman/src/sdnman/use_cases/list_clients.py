"""Use case: list clients with search and pagination."""

from __future__ import annotations

from ..dtos import ClientRow, PagedClients
from ..entities import Client
from ..formatters import humanize_uptime
from ..services import NetworkStateService


def _to_row(client: Client) -> ClientRow:
    return ClientRow(
        id=client.id,
        name=client.name,
        mac=str(client.mac),
        ip=str(client.ip) if client.ip else "-",
        status=client.status.value,
        network=client.network,
        ssid=client.ssid,
        ap_or_port=client.ap_or_port,
        activity=client.activity.humanize(),
        downloaded=client.downloaded.humanize(),
        uploaded=client.uploaded.humanize(),
        uptime=humanize_uptime(client.uptime_seconds),
        connection=client.connection.value,
    )


class ListClients:
    """Return clients, optionally filtered by a search term, paginated."""

    def __init__(self, network: NetworkStateService) -> None:
        self._network = network

    def execute(
        self, search: str = "", page: int = 1, page_size: int = 10
    ) -> PagedClients:
        page = max(1, page)
        page_size = max(1, page_size)
        clients = self._network.clients()

        term = search.strip().lower()
        if term:
            clients = [c for c in clients if self._matches(c, term)]

        total = len(clients)
        start = (page - 1) * page_size
        end = start + page_size
        rows = [_to_row(c) for c in clients[start:end]]
        return PagedClients(rows=rows, page=page, page_size=page_size, total=total)

    @staticmethod
    def _matches(client: Client, term: str) -> bool:
        haystack = " ".join(
            [
                client.name,
                str(client.mac),
                str(client.ip) if client.ip else "",
                client.network,
                client.ssid,
            ]
        ).lower()
        return term in haystack
