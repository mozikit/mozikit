"""Stable per-user paths for Mozikit runtime infrastructure."""

import os
from pathlib import Path


def get_app_data_dir() -> Path:
    override = os.environ.get("MOZIKIT_APP_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "Mozikit"
    return Path.home() / ".local" / "share" / "Mozikit"


def get_runtime_dir() -> Path:
    return get_app_data_dir() / "runtime"
