from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from src.core.update_manager import UpdateError, UpdateManager, parse_version


class _Response:
    def __init__(self, payload: bytes, status: int = 200):
        self.payload = payload
        self.status = status
        self.offset = 0

    def getcode(self):
        return self.status

    def read(self, size: int = -1):
        if size < 0:
            size = len(self.payload) - self.offset
        chunk = self.payload[self.offset : self.offset + size]
        self.offset += len(chunk)
        return chunk

    def close(self):
        return None


def _release(
    *,
    version: str,
    tag: str,
    source_ref: str,
    sequence: int,
    payload: bytes = b"msi payload",
    published_at: str = "2026-09-23T10:00:00Z",
):
    asset_name = f"mozikit-{tag}-x64.msi"
    asset_url = f"https://github.com/mozikit/mozikit/releases/download/{tag}/{asset_name}"
    digest = hashlib.sha256(payload).hexdigest()
    manifest = {
        "schema": 1,
        "minimum_updater": 1,
        "platform": "windows-x64",
        "channel": "nightly" if "-nightly." in tag else "stable",
        "tag": tag,
        "version": version,
        "source_ref": source_ref,
        "build_sequence": sequence,
        "upgrade": {
            "method": "msi",
            "preserves_user_data": True,
        },
        "assets": [
            {
                "name": asset_name,
                "kind": "msi",
                "platform": "windows-x64",
                "url": asset_url,
                "sha256": digest,
                "size": len(payload),
            }
        ],
    }
    return {
        "id": sequence,
        "tag_name": tag,
        "draft": False,
        "prerelease": "-nightly." in tag,
        "published_at": published_at,
        "manifest": manifest,
        "assets": [
            {"name": asset_name, "browser_download_url": asset_url},
        ],
    }, asset_url, payload


def _manager(tmp_path: Path, releases: list[dict], asset_url: str, payload: bytes):
    api_url = "https://api.github.com/repos/mozikit/mozikit/releases?per_page=100"

    def opener(request, timeout=0):
        url = request.full_url
        if url == api_url:
            return _Response(json.dumps(releases).encode("utf-8"))
        if url == asset_url:
            return _Response(payload)
        raise AssertionError(f"unexpected URL: {url}")

    return UpdateManager(
        opener=opener,
        data_dir=tmp_path / "appdata",
        platform="win32",
        frozen=True,
        executable=tmp_path / "Mozikit" / "mozikit.exe",
    )


def test_parse_version_distinguishes_stable_and_nightly():
    assert parse_version("0.2.6").nightly is False
    nightly = parse_version("0.2.6-nightly.20260923.3709934")
    assert nightly.nightly is True
    assert nightly.nightly_date == 20260923


def test_nightly_check_uses_build_sequence_and_never_hash_order(tmp_path):
    old, _, payload = _release(
        version="0.2.6-nightly.20260923.aaaaaaa",
        tag="v0.2.6-nightly.20260923.aaaaaaa",
        source_ref="a" * 40,
        sequence=10,
        published_at="2026-09-23T10:00:00Z",
    )
    new, asset_url, payload = _release(
        version="0.2.6-nightly.20260923.1111111",
        tag="v0.2.6-nightly.20260923.1111111",
        source_ref="b" * 40,
        sequence=11,
        published_at="2026-09-23T10:01:00Z",
        payload=payload,
    )
    manager = _manager(tmp_path, [old, new], asset_url, payload)
    manager._read_msi_install_path = lambda: str(tmp_path / "Mozikit")

    result = manager.check(
        channel="nightly",
        current_version="0.2.6-nightly.20260923.aaaaaaa",
    )

    assert result.available is True
    assert result.latest_version == "0.2.6-nightly.20260923.1111111"
    assert result.candidate is not None
    assert result.candidate.build_sequence == 11
    assert result.can_install is True


def test_nightly_same_sequence_with_different_source_ref_is_invalid(tmp_path):
    first, asset_url, payload = _release(
        version="0.2.6-nightly.20260923.aaaaaaa",
        tag="v0.2.6-nightly.20260923.aaaaaaa",
        source_ref="a" * 40,
        sequence=10,
    )
    second, _, _ = _release(
        version="0.2.6-nightly.20260923.bbbbbbb",
        tag="v0.2.6-nightly.20260923.bbbbbbb",
        source_ref="b" * 40,
        sequence=10,
    )
    manager = _manager(tmp_path, [first, second], asset_url, payload)

    with pytest.raises(UpdateError, match="多个 source_ref") as exc_info:
        manager.check(channel="nightly", current_version="0.2.5-nightly.20260922.aaaaaaa")
    assert exc_info.value.code == "invalid_manifest"


def test_download_verifies_sha256_and_install_handoff_is_detached(tmp_path):
    release, asset_url, payload = _release(
        version="0.2.7-nightly.20260923.1111111",
        tag="v0.2.7-nightly.20260923.1111111",
        source_ref="c" * 40,
        sequence=12,
    )
    calls = []

    def popen(args, **kwargs):
        calls.append((args, kwargs))

        class Process:
            pid = 4321

        return Process()

    manager = _manager(tmp_path, [release], asset_url, payload)
    manager._read_msi_install_path = lambda: str(tmp_path / "Mozikit")
    manager._find_msiexec = lambda: "C:/Windows/System32/msiexec.exe"
    manager._popen = popen

    checked = manager.check(
        channel="nightly",
        current_version="0.2.6-nightly.20260923.aaaaaaa",
    )
    installed = manager.download_and_install(checked, quiet=True)

    assert installed.status == "pending_install"
    assert installed.downloaded_path is not None
    assert Path(installed.downloaded_path).is_file()
    assert calls[0][0][0].endswith("msiexec.exe")
    assert "/quiet" in calls[0][0]
    assert calls[0][1]["stdout"] is not None
    assert json.loads(manager.state_path.read_text(encoding="utf-8"))["status"] == "pending_install"


def test_portable_check_is_available_but_blocked_for_install(tmp_path):
    release, asset_url, payload = _release(
        version="0.2.7-nightly.20260923.1111111",
        tag="v0.2.7-nightly.20260923.1111111",
        source_ref="c" * 40,
        sequence=12,
    )
    manager = _manager(tmp_path, [release], asset_url, payload)
    result = manager.check(
        channel="nightly",
        current_version="0.2.6-nightly.20260923.aaaaaaa",
    )

    assert result.available is True
    assert result.installation is not None
    assert result.installation.kind == "portable"
    assert result.can_install is False
