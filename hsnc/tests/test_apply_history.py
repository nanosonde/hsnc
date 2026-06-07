"""Tests for the apply-history listing use case."""

from __future__ import annotations

from datetime import UTC, datetime

from hsnc.entities import ApplyEvent, ApplyOutcome
from hsnc.use_cases.apply_history import ListApplyHistory

from .fakes import FakeApplyHistoryStore


def _event(username: str, ok: bool) -> ApplyEvent:
    return ApplyEvent(
        applied_at=datetime.now(UTC),
        username=username,
        ok=ok,
        outcomes=[ApplyOutcome("d1", "Device 1", ok=ok)],
    )


def test_list_returns_events_newest_first():
    store = FakeApplyHistoryStore()
    store.record_apply_event(_event("admin", True))
    store.record_apply_event(_event("admin", False))

    events = ListApplyHistory(store).execute()
    assert len(events) == 2
    # newest first
    assert events[0].ok is False
    assert events[1].ok is True


def test_list_respects_limit():
    store = FakeApplyHistoryStore()
    for _ in range(5):
        store.record_apply_event(_event("admin", True))

    assert len(ListApplyHistory(store).execute(limit=3)) == 3
