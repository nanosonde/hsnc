"""Use case: delete a device from the inventory.

Removes the device from the declarative configuration (YAML) and drops it from
the applied snapshot so it no longer appears in the pending-changes diff.
"""

from __future__ import annotations

from ...domain.interfaces import AppliedConfigStore, ConfigWriter


class DeleteDevice:
    """Remove a single device from the inventory and applied snapshot."""

    def __init__(self, writer: ConfigWriter, applied: AppliedConfigStore) -> None:
        self._writer = writer
        self._applied = applied

    def execute(self, device_id: str) -> None:
        self._writer.delete_device(device_id)
        snapshot = [d for d in self._applied.load() if d.id != device_id]
        self._applied.save(snapshot)
