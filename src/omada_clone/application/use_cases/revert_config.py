"""Use case: revert pending changes back to the last applied snapshot.

Restores each device's desired configuration (YAML) to the version recorded in
the applied snapshot, discarding edits that have not been applied. Each restored
device is written through the :class:`ConfigWriter`, which validates and takes a
timestamped backup. Returns the number of devices reverted (0 if nothing was
ever applied or there is nothing to revert).
"""

from __future__ import annotations

from ...domain.interfaces import AppliedConfigStore, ConfigRepository, ConfigWriter


class RevertPendingChanges:
    """Discard unapplied edits, restoring the last applied configuration."""

    def __init__(
        self,
        config: ConfigRepository,
        applied: AppliedConfigStore,
        writer: ConfigWriter,
    ) -> None:
        self._config = config
        self._applied = applied
        self._writer = writer

    def execute(self) -> int:
        applied = self._applied.load()
        if not applied:
            return 0
        desired = {d.id: d for d in self._config.list_devices()}
        reverted = 0
        for device in applied:
            if desired.get(device.id) != device:
                self._writer.save_device(device)
                reverted += 1
        return reverted
