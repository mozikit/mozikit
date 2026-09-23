from __future__ import annotations

import json

from typer.testing import CliRunner

from src.cli import app
from src.core.update_manager import Installation, UpdateCandidate, UpdateResult


def _candidate() -> UpdateCandidate:
    from src.core.update_manager import UpdateAsset

    return UpdateCandidate(
        channel="nightly",
        tag="v0.2.7-nightly.20260923.1111111",
        version="0.2.7-nightly.20260923.1111111",
        source_ref="a" * 40,
        assets=(
            UpdateAsset(
                name="mozikit-v0.2.7-nightly.20260923.1111111-x64.msi",
                kind="msi",
                url="https://github.com/mozikit/mozikit/releases/download/x/msi",
                sha256="0" * 64,
                size=1,
            ),
        ),
        build_sequence=12,
        published_at="2026-09-23T10:00:00Z",
    )


def test_update_check_json_is_one_machine_readable_document(monkeypatch):
    candidate = _candidate()
    installation = Installation("msi", r"C:\Mozikit\mozikit.exe", r"C:\Mozikit", True)

    class FakeManager:
        default_channel = "nightly"
        current_version = "0.2.6-nightly.20260923.aaaaaaa"

        def check(self, *, channel=None):
            return UpdateResult(
                status="update_available",
                channel=channel or "nightly",
                current_version=self.current_version,
                latest_version=candidate.version,
                candidate=candidate,
                installation=installation,
                can_install=True,
                message="发现可用更新。",
                checked_at="2026-09-23T10:00:00Z",
            )

    monkeypatch.setattr("src.core.update_manager.UpdateManager", FakeManager)
    result = CliRunner().invoke(app, ["update", "--check", "--channel", "nightly", "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "update_available"
    assert payload["candidate"]["build_sequence"] == 12
    assert "更新状态" not in result.stdout


def test_update_yes_returns_pending_install_exit_code(monkeypatch):
    candidate = _candidate()
    installation = Installation("msi", r"C:\Mozikit\mozikit.exe", r"C:\Mozikit", True)

    class FakeManager:
        default_channel = "nightly"

        def check(self, *, channel=None):
            return UpdateResult(
                status="update_available",
                channel="nightly",
                current_version="0.2.6-nightly.20260923.aaaaaaa",
                latest_version=candidate.version,
                candidate=candidate,
                installation=installation,
                can_install=True,
            )

        def download_and_install(self, result, *, quiet=False):
            assert quiet is True
            return UpdateResult(
                status="pending_install",
                channel="nightly",
                current_version=result.current_version,
                latest_version=result.latest_version,
                candidate=result.candidate,
                installation=installation,
                can_install=True,
                downloaded_path=r"C:\Users\test\Mozikit\updates\update.msi",
            )

    monkeypatch.setattr("src.core.update_manager.UpdateManager", FakeManager)
    result = CliRunner().invoke(app, ["update", "--yes", "--json"])

    assert result.exit_code == 3, result.output
    assert json.loads(result.stdout)["status"] == "pending_install"


def test_update_requires_yes_in_json_mode(monkeypatch):
    candidate = _candidate()
    installation = Installation("msi", r"C:\Mozikit\mozikit.exe", r"C:\Mozikit", True)

    class FakeManager:
        default_channel = "nightly"

        def check(self, *, channel=None):
            return UpdateResult(
                status="update_available",
                channel="nightly",
                current_version="0.2.6-nightly.20260923.aaaaaaa",
                latest_version=candidate.version,
                candidate=candidate,
                installation=installation,
                can_install=True,
            )

    monkeypatch.setattr("src.core.update_manager.UpdateManager", FakeManager)
    result = CliRunner().invoke(app, ["update", "--json"])

    assert result.exit_code == 2, result.output
    payload = json.loads(result.stdout)
    assert payload["status"] == "blocked"
    assert payload["error"]["code"] == "confirmation_required"
