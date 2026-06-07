"""Backend settings resolution from environment variables with defaults."""

from __future__ import annotations

import os
from pathlib import Path

from ..container import Settings
from ..devices.ssh_transport import SshConnectionSettings


def settings_from_env() -> Settings:
    base = Path(__file__).resolve().parents[3]
    config_dir = Path(os.environ.get("SDNMAN_CONFIG_DIR", base / "config"))
    data_dir = Path(os.environ.get("SDNMAN_DATA_DIR", base / "data"))
    use_mock = os.environ.get("SDNMAN_USE_MOCK_DEVICES", "1") not in ("0", "false", "False")
    poll_interval = int(os.environ.get("SDNMAN_POLL_INTERVAL", "30"))
    retention_days = int(os.environ.get("SDNMAN_RETENTION_DAYS", "30"))
    baseline_on_start = os.environ.get("SDNMAN_BASELINE_ON_START", "1") not in (
        "0",
        "false",
        "False",
    )
    return Settings(
        config_dir=config_dir,
        data_dir=data_dir,
        use_mock_devices=use_mock,
        poll_interval_seconds=poll_interval,
        retention_days=retention_days,
        baseline_on_start=baseline_on_start,
        ssh=SshConnectionSettings.from_env(),
    )
