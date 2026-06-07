"""Settings resolution from environment variables with sensible defaults."""

from __future__ import annotations

import os
from pathlib import Path

from ..infrastructure.container import Settings
from ..infrastructure.devices.ssh_transport import SshConnectionSettings


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
    broker_socket = Path(os.environ.get("SDNMAN_BROKER_SOCKET", data_dir / "broker.sock"))
    api_base_url = os.environ.get("SDNMAN_API_BASE_URL", "http://127.0.0.1:8081")
    api_token = os.environ.get("SDNMAN_API_TOKEN", "")
    return Settings(
        config_dir=config_dir,
        data_dir=data_dir,
        use_mock_devices=use_mock,
        poll_interval_seconds=poll_interval,
        retention_days=retention_days,
        baseline_on_start=baseline_on_start,
        broker_socket=broker_socket,
        api_base_url=api_base_url,
        api_token=api_token,
        ssh=SshConnectionSettings.from_env(),
    )

