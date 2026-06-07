"""Use case: list recorded configuration-apply runs (history / audit)."""

from __future__ import annotations

from ..entities import ApplyEvent
from ..interfaces import ApplyHistoryStore


class ListApplyHistory:
    """Return the most recent apply runs, newest first."""

    def __init__(self, history: ApplyHistoryStore) -> None:
        self._history = history

    def execute(self, limit: int = 50) -> list[ApplyEvent]:
        return self._history.list_apply_events(limit)
