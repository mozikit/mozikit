"""Windows CLI discoverability for installed and portable Mozikit builds.

The MSI owns the machine-wide PATH entry for installed builds.  This module
owns the cross-installer capability used by portable builds and future
installers, using only the current user's PATH so it never needs elevation.
"""

from __future__ import annotations

import ctypes
import os
import sys
from pathlib import Path


CLI_EXE_NAME = "mozikit.exe" if os.name == "nt" else "mozikit"
_ENVIRONMENT_KEY = r"Environment"


def get_cli_executable_path() -> Path | None:
    """Return the frozen CLI executable next to the current launcher."""
    if not getattr(sys, "frozen", False):
        return None
    return Path(sys.executable).resolve().parent / CLI_EXE_NAME


def _normalise_path(value: str | os.PathLike[str]) -> str:
    value = str(value).strip().strip('"')
    try:
        return os.path.normcase(os.path.normpath(str(Path(value).expanduser())))
    except (TypeError, ValueError):
        return os.path.normcase(os.path.normpath(value))


def split_path_entries(value: str | None) -> list[str]:
    """Split a PATH value while ignoring empty entries."""
    if not value:
        return []
    return [entry.strip().strip('"') for entry in value.split(os.pathsep) if entry.strip()]


def merge_path_entry(value: str | None, entry: str) -> str:
    """Append ``entry`` once, preserving every unrelated PATH entry."""
    entries = split_path_entries(value)
    entry_key = _normalise_path(entry)
    if not any(_normalise_path(item) == entry_key for item in entries):
        entries.append(str(entry))
    return os.pathsep.join(entries)


def remove_path_entry(value: str | None, entry: str) -> str:
    """Remove only the exact normalized directory owned by Mozikit."""
    entry_key = _normalise_path(entry)
    return os.pathsep.join(
        item for item in split_path_entries(value) if _normalise_path(item) != entry_key
    )


def _read_registry_path(root, winreg) -> str:
    try:
        with winreg.OpenKey(root, _ENVIRONMENT_KEY, 0, winreg.KEY_READ) as key:
            value, _ = winreg.QueryValueEx(key, "Path")
            return str(value or "")
    except (FileNotFoundError, OSError):
        return ""


def _registry_paths(winreg) -> list[tuple[str, str]]:
    result = []
    for scope, root in (("user", winreg.HKEY_CURRENT_USER), ("system", winreg.HKEY_LOCAL_MACHINE)):
        value = _read_registry_path(root, winreg)
        if value:
            result.append((scope, value))
    return result


def _source_for_locations(locations: list[str]) -> str | None:
    """Classify PATH ownership without allowing user registration to shadow MSI."""
    has_user = "user" in locations
    has_system = "system" in locations
    if has_system and has_user:
        return "installer+user"
    if has_system:
        return "installer"
    if has_user:
        return "user"
    return None


def _broadcast_environment_change() -> None:
    if os.name != "nt":
        return
    try:
        HWND_BROADCAST = 0xFFFF
        WM_SETTINGCHANGE = 0x001A
        SMTO_ABORTIFHUNG = 0x0002
        ctypes.windll.user32.SendMessageTimeoutW(
            HWND_BROADCAST,
            WM_SETTINGCHANGE,
            0,
            "Environment",
            SMTO_ABORTIFHUNG,
            1000,
            None,
        )
    except (AttributeError, OSError):
        # PATH is already persisted; a new terminal will see it even when the
        # optional broadcast is unavailable (for example in a service context).
        pass


def _write_user_path(value: str) -> None:
    if os.name != "nt":
        raise RuntimeError("CLI registration is currently supported on Windows only")
    import winreg

    with winreg.CreateKeyEx(
        winreg.HKEY_CURRENT_USER,
        _ENVIRONMENT_KEY,
        0,
        winreg.KEY_READ | winreg.KEY_WRITE,
    ) as key:
        winreg.SetValueEx(key, "Path", 0, winreg.REG_EXPAND_SZ, value)
    _broadcast_environment_change()


def get_cli_registration_status() -> dict:
    """Return ``registered``, ``not registered`` or ``broken`` status."""
    target = get_cli_executable_path()
    if os.name != "nt":
        return {
            "status": "not registered",
            "source": None,
            "path": str(target) if target else None,
            "locations": [],
        }
    if target is None:
        return {"status": "not registered", "source": None, "path": None, "locations": []}

    import winreg

    target_dir = str(target.parent)
    locations = [
        scope
        for scope, value in _registry_paths(winreg)
        if any(_normalise_path(item) == _normalise_path(target_dir) for item in split_path_entries(value))
    ]
    if not locations:
        return {"status": "not registered", "source": None, "path": str(target), "locations": []}
    source = _source_for_locations(locations)
    if not target.is_file():
        return {"status": "broken", "source": source, "path": str(target), "locations": locations}
    return {"status": "registered", "source": source, "path": str(target), "locations": locations}


def register_cli() -> dict:
    """Register the current frozen CLI directory in the user PATH."""
    target = get_cli_executable_path()
    if target is None:
        raise RuntimeError("源码环境没有可注册的 mozikit.exe；请从 Desktop/Portable 发行版运行")
    if not target.is_file():
        raise RuntimeError(f"CLI executable not found: {target}")
    import winreg

    system_path = _read_registry_path(winreg.HKEY_LOCAL_MACHINE, winreg)
    if any(
        _normalise_path(item) == _normalise_path(str(target.parent))
        for item in split_path_entries(system_path)
    ):
        # MSI already owns this registration. Do not add a redundant user PATH
        # entry, and let ``cli uninstall`` leave the installer registration intact.
        return get_cli_registration_status()

    current = _read_registry_path(winreg.HKEY_CURRENT_USER, winreg)
    _write_user_path(merge_path_entry(current, str(target.parent)))
    return get_cli_registration_status()


def unregister_cli() -> dict:
    """Remove only the current user's Mozikit PATH entry."""
    target = get_cli_executable_path()
    if target is None:
        raise RuntimeError("源码环境没有可移除的 mozikit.exe 注册")
    import winreg

    current = _read_registry_path(winreg.HKEY_CURRENT_USER, winreg)
    if current:
        _write_user_path(remove_path_entry(current, str(target.parent)))
    return get_cli_registration_status()
