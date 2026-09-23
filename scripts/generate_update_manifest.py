#!/usr/bin/env python3
"""Generate the channel-aware release metadata consumed by Mozikit updaters.

The manifest describes downloadable artifacts and the existing Mozikit
upgrade boundary.  MSI remains installer-managed and Portable ZIP remains
user-managed, while the shared updater handles discovery and verification.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from urllib.parse import quote


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_manifest(
    release_dir: Path,
    *,
    tag: str,
    version: str,
    source_ref: str,
    repository: str,
    build_sequence: int | None = None,
    platform: str = "windows-x64",
) -> dict:
    artifacts = sorted(
        path
        for path in release_dir.iterdir()
        if path.is_file() and path.suffix.lower() in {".msi", ".zip"}
    )
    if not artifacts:
        raise ValueError(f"No MSI or ZIP artifacts found in {release_dir}")

    channel = "nightly" if "-nightly." in tag else "stable"
    assets = [
        {
            "name": path.name,
            "kind": "msi" if path.suffix.lower() == ".msi" else "portable",
            "platform": platform,
            "url": (
                f"https://github.com/{repository}/releases/download/"
                f"{quote(tag, safe='')}/{quote(path.name, safe='')}"
            ),
            "sha256": sha256(path),
            "size": path.stat().st_size,
        }
        for path in artifacts
    ]

    manifest = {
        "schema": 1,
        "minimum_updater": 1,
        "platform": platform,
        "channel": channel,
        "tag": tag,
        "version": version,
        "source_ref": source_ref,
        "assets": assets,
        "upgrade": {
            "method": "msi",
            "preserves_user_data": True,
            "user_data_dir": "%LOCALAPPDATA%\\Mozikit",
            "portable_requires_manual_replace": True,
        },
    }
    if build_sequence is not None:
        if build_sequence < 0:
            raise ValueError("build_sequence must be non-negative")
        manifest["build_sequence"] = build_sequence
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--build-sequence", type=int)
    parser.add_argument("--platform", default="windows-x64")
    args = parser.parse_args()

    manifest = build_manifest(
        args.release_dir,
        tag=args.tag,
        version=args.version,
        source_ref=args.source_ref,
        repository=args.repository,
        build_sequence=args.build_sequence,
        platform=args.platform,
    )
    output = args.release_dir / "update-manifest.json"
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output} ({len(manifest['assets'])} assets, channel={manifest['channel']})")


if __name__ == "__main__":
    main()
