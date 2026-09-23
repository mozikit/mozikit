from __future__ import annotations

import json
from pathlib import Path

from scripts.generate_update_manifest import build_manifest


def test_nightly_manifest_describes_assets_and_upgrade_boundary(tmp_path: Path):
    msi = tmp_path / "mozikit-v0.2.6-nightly.20260923.31ef182-x64.msi"
    portable = tmp_path / "Mozikit-Windows-x64.zip"
    msi.write_bytes(b"msi")
    portable.write_bytes(b"zip")

    manifest = build_manifest(
        tmp_path,
        tag="v0.2.6-nightly.20260923.31ef182",
        version="0.2.6-nightly.20260923.31ef182",
        source_ref="3" * 40,
        repository="mozikit/mozikit",
        build_sequence=42,
    )

    assert manifest["schema"] == 1
    assert manifest["channel"] == "nightly"
    assert manifest["platform"] == "windows-x64"
    assert manifest["build_sequence"] == 42
    assert manifest["source_ref"] == "3" * 40
    assert manifest["upgrade"]["user_data_dir"] == "%LOCALAPPDATA%\\Mozikit"
    assert {asset["kind"] for asset in manifest["assets"]} == {"msi", "portable"}
    assert all(len(asset["sha256"]) == 64 for asset in manifest["assets"])
    assert all("/releases/download/v0.2.6-nightly.20260923.31ef182/" in asset["url"] for asset in manifest["assets"])


def test_stable_manifest_uses_stable_channel(tmp_path: Path):
    (tmp_path / "mozikit-v0.2.6-x64.msi").write_bytes(b"msi")

    manifest = build_manifest(
        tmp_path,
        tag="v0.2.6",
        version="0.2.6",
        source_ref="4" * 40,
        repository="mozikit/mozikit",
    )

    assert manifest["channel"] == "stable"
    assert manifest["platform"] == "windows-x64"
