#!/usr/bin/env python3
"""Generate the channel-aware release metadata consumed by future updaters.

The manifest deliberately describes downloadable artifacts and the existing
Mozikit upgrade boundary.  It does not perform an update itself: MSI remains
installer-managed and Portable ZIP remains user-managed.
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
            "url": (
                f"https://github.com/{repository}/releases/download/"
                f"{quote(tag, safe='')}/{quote(path.name, safe='')}"
            ),
            "sha256": sha256(path),
            "size": path.stat().st_size,
        }
        for path in artifacts
    ]

    return {
        "schema": 1,
        "minimum_updater": 1,
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release-dir", type=Path, required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--version", required=True)
    parser.add_argument("--source-ref", required=True)
    parser.add_argument("--repository", required=True)
    args = parser.parse_args()

    manifest = build_manifest(
        args.release_dir,
        tag=args.tag,
        version=args.version,
        source_ref=args.source_ref,
        repository=args.repository,
    )
    output = args.release_dir / "update-manifest.json"
    output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output} ({len(manifest['assets'])} assets, channel={manifest['channel']})")


if __name__ == "__main__":
    main()
