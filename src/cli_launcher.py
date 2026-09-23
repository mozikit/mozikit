"""Frozen console launcher for the first-class ``mozikit`` CLI."""

import sys


def _configure_console_streams() -> None:
    """Make frozen CLI output deterministic for pipes and Windows consoles.

    PyInstaller's console bootloader can inherit a legacy Windows code page
    even when ``PYTHONUTF8`` is set in the parent process.  Rich's Windows
    renderer then raises while formatting the Chinese help text.  Configure
    the standard streams before importing Typer/Rich so both human terminals
    and machine consumers receive UTF-8 output.
    """
    for stream_name in ("stdout", "stderr"):
        stream = getattr(sys, stream_name, None)
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            # A host may expose a non-reconfigurable stream.  The CLI should
            # still start and let the stream's native behavior decide output.
            continue


_configure_console_streams()

from src.core.runtime_paths import migrate_legacy_app_data

migrate_legacy_app_data()

from src.cli import run_cli


def main() -> None:
    migrate_legacy_app_data()
    run_cli()


if __name__ == "__main__":
    main()
