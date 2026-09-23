"""Stable per-user paths for Mozikit runtime infrastructure."""

import os
import shutil
from pathlib import Path


def get_app_data_dir() -> Path:
    override = os.environ.get("MOZIKIT_APP_DATA_DIR")
    if override:
        return Path(override).expanduser().resolve()
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return Path(base) / "Mozikit"
        # Real Windows user sessions provide LOCALAPPDATA. Keep the legacy
        # Roaming-shaped fallback for stripped-down service/test hosts where
        # neither Windows environment variable is available.
        return Path.home() / "AppData" / "Roaming" / "Mozikit"
    return Path.home() / ".local" / "share" / "Mozikit"


def get_runtime_dir() -> Path:
    return get_app_data_dir() / "runtime"


def get_workspace_dir() -> Path:
    """Return the default workspace for a frozen Desktop installation.

    Source checkouts intentionally keep the historical ``./workflows``
    behavior in :func:`src.core.resolve_workspace`; installed applications
    must never use their read-only install directory as the default workspace.
    """
    return get_app_data_dir() / "workflows"


def migrate_legacy_app_data() -> bool:
    """Copy missing data from the old Roaming location into LocalAppData.

    Older frozen GUI builds used ``%APPDATA%\\Mozikit`` as their working
    directory.  The Desktop contract uses ``%LOCALAPPDATA%\\Mozikit``.  The
    migration is additive: existing files in the new location win, and the
    old directory is never removed.
    """
    if os.name != "nt" or os.environ.get("MOZIKIT_APP_DATA_DIR"):
        return False

    local_base = os.environ.get("LOCALAPPDATA")
    roaming_base = os.environ.get("APPDATA")
    if not local_base or not roaming_base:
        return False

    target = Path(local_base) / "Mozikit"
    legacy = Path(roaming_base) / "Mozikit"
    try:
        if not legacy.is_dir() or target.resolve() == legacy.resolve():
            return False
    except OSError:
        return False

    copied = False
    try:
        target.mkdir(parents=True, exist_ok=True)
        for source in legacy.rglob("*"):
            relative = source.relative_to(legacy)
            if relative.parts and relative.parts[0] in {"runtime", "logs"}:
                # Daemon connection state and logs are machine/process-local;
                # carrying them across locations can resurrect stale PIDs.
                continue
            destination = target / relative
            if source.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            elif source.is_file() and not destination.exists():
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                copied = True
    except OSError:
        # A locked or partially accessible legacy directory must not prevent
        # the application from starting with its normal fresh data path.
        return copied
    return copied


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
