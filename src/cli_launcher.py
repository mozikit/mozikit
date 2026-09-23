"""Frozen console launcher for the first-class ``mozikit`` CLI."""

from src.core.runtime_paths import migrate_legacy_app_data

migrate_legacy_app_data()

from src.cli import run_cli


def main() -> None:
    migrate_legacy_app_data()
    run_cli()


if __name__ == "__main__":
    main()
