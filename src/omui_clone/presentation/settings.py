"""Settings resolution from environment variables with sensible defaults."""

from __future__ import annotations

import os
from pathlib import Path

from ..infrastructure.container import Settings


def settings_from_env() -> Settings:
    base = Path(__file__).resolve().parents[3]
    config_dir = Path(os.environ.get("OMUI_CONFIG_DIR", base / "config"))
    data_dir = Path(os.environ.get("OMUI_DATA_DIR", base / "data"))
    use_mock = os.environ.get("OMUI_USE_MOCK_DEVICES", "1") not in ("0", "false", "False")
    poll_interval = int(os.environ.get("OMUI_POLL_INTERVAL", "30"))
    return Settings(
        config_dir=config_dir,
        data_dir=data_dir,
        use_mock_devices=use_mock,
        poll_interval_seconds=poll_interval,
    )
