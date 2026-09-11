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


def get_config_path() -> Path:
    """Return the single absolute application configuration path."""
    override = os.environ.get("MOZIKIT_CONFIG_PATH")
    if override:
        return Path(override).expanduser().resolve()
    return get_app_data_dir() / "config.json"


def get_mcp_dir() -> Path:
    """Return the application-owned directory for MCP configuration."""
    return get_app_data_dir() / "mcp"


def get_mcp_servers_path() -> Path:
    """Return the persistent MCP Server Registry file path."""
    return get_mcp_dir() / "servers.json"
