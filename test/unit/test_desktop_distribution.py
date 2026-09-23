"""Regression coverage for the Windows Desktop distribution contract."""

import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from src.cli import app
from src.core.cli_registration import _source_for_locations, merge_path_entry, remove_path_entry
from src.core.runtime_paths import migrate_legacy_app_data
from src.core.node_registry import NodeRegistry
from src.core.uv_manager import UVManager, get_bundled_uv_path


def _uv_manager() -> UVManager:
    """Build a dependency-free manager for path precedence tests."""
    manager = UVManager.__new__(UVManager)
    manager.custom_uv_path = None
    manager._verify_uv_executable = lambda path: True
    return manager


def test_launchers_delegate_to_their_single_adapter(monkeypatch):
    import src.cli_launcher as cli_launcher
    import src.gui_launcher as gui_launcher

    cli_called = []
    gui_called = []
    monkeypatch.setattr(cli_launcher, "run_cli", lambda: cli_called.append(True))
    monkeypatch.setattr(gui_launcher, "run_gui", lambda: gui_called.append(True))

    cli_launcher.main()
    gui_launcher.main()

    assert cli_called == [True]
    assert gui_called == [True]


def test_cli_launcher_configures_utf8_console_streams(monkeypatch):
    import src.cli_launcher as cli_launcher

    class FakeStream:
        def __init__(self):
            self.calls = []

        def reconfigure(self, **kwargs):
            self.calls.append(kwargs)

    stdout = FakeStream()
    stderr = FakeStream()
    monkeypatch.setattr(cli_launcher.sys, "stdout", stdout)
    monkeypatch.setattr(cli_launcher.sys, "stderr", stderr)

    cli_launcher._configure_console_streams()

    assert stdout.calls == [{"encoding": "utf-8", "errors": "replace"}]
    assert stderr.calls == [{"encoding": "utf-8", "errors": "replace"}]


def test_bundled_uv_path_uses_frozen_runtime_directory(tmp_path, monkeypatch):
    install_dir = tmp_path / "Mozikit"
    uv_path = install_dir / "runtime" / "uv.exe"
    uv_path.parent.mkdir(parents=True)
    uv_path.write_bytes(b"bundled uv test marker")

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", str(install_dir / "mozikit.exe"))
    monkeypatch.delenv("MOZIKIT_BUNDLED_UV_PATH", raising=False)

    assert get_bundled_uv_path() == uv_path.resolve()


def test_legacy_roaming_data_is_copied_without_overwriting_local_data(tmp_path, monkeypatch):
    roaming = tmp_path / "Roaming"
    local = tmp_path / "Local"
    legacy_config = roaming / "Mozikit" / "config.json"
    legacy_workflow = roaming / "Mozikit" / "workflows" / "demo.json"
    legacy_workflow.parent.mkdir(parents=True)
    legacy_config.write_text('{"old": true}', encoding="utf-8")
    legacy_workflow.write_text('{"workflow_name": "demo"}', encoding="utf-8")

    target_config = local / "Mozikit" / "config.json"
    target_config.parent.mkdir(parents=True)
    target_config.write_text('{"new": true}', encoding="utf-8")
    monkeypatch.setenv("APPDATA", str(roaming))
    monkeypatch.setenv("LOCALAPPDATA", str(local))
    monkeypatch.delenv("MOZIKIT_APP_DATA_DIR", raising=False)

    assert migrate_legacy_app_data() is True
    assert json.loads(target_config.read_text(encoding="utf-8")) == {"new": True}
    assert (local / "Mozikit" / "workflows" / "demo.json").is_file()


def test_frozen_node_registry_uses_app_data_not_install_cwd(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setenv("MOZIKIT_APP_DATA_DIR", str(tmp_path / "appdata"))

    registry = NodeRegistry()

    assert registry._user_data_dir == (tmp_path / "appdata" / "user_data").resolve()


def test_uv_resolution_precedence(tmp_path, monkeypatch):
    selected = tmp_path / "selected.exe"
    custom = tmp_path / "custom.exe"
    bundled = tmp_path / "bundled.exe"
    path_uv = tmp_path / "path.exe"
    common = tmp_path / "common.exe"
    for candidate in (selected, custom, bundled, path_uv, common):
        candidate.write_bytes(b"uv")

    manager = _uv_manager()
    manager.custom_uv_path = str(custom)
    manager.get_bundled_uv_path = lambda: str(bundled)
    manager._find_path_uv_installations = lambda: [str(path_uv)]
    manager._get_common_uv_paths = lambda: [str(common)]

    assert manager.find_uv_installations() == [
        str(custom),
        str(bundled),
        str(path_uv),
        str(common),
    ]
    assert manager.get_preferred_uv_path(str(selected)) == str(selected)
    assert manager.get_preferred_uv_path() == str(custom)

    manager.custom_uv_path = None
    assert manager.get_preferred_uv_path() == str(bundled)

    manager.get_bundled_uv_path = lambda: None
    assert manager.get_preferred_uv_path() == str(path_uv)

    manager._find_path_uv_installations = lambda: []
    assert manager.get_preferred_uv_path() == str(common)

    manager._get_common_uv_paths = lambda: []
    assert manager.get_preferred_uv_path() is None


def test_cli_registration_path_helpers_preserve_unrelated_entries():
    original = os.pathsep.join([r"C:\Windows\System32", r"C:\Tools"])
    merged = merge_path_entry(original, r"C:\Mozikit")
    merged_again = merge_path_entry(merged, r"c:\mozikit\.")

    assert merged_again.count(r"C:\Mozikit") == 1
    assert r"C:\Windows\System32" in merged_again
    assert r"C:\Tools" in merged_again
    assert remove_path_entry(merged_again, r"C:\Mozikit") == original


def test_cli_registration_reports_msi_and_user_ownership_separately():
    assert _source_for_locations([]) is None
    assert _source_for_locations(["user"]) == "user"
    assert _source_for_locations(["system"]) == "installer"
    assert _source_for_locations(["user", "system"]) == "installer+user"


def test_bundled_uv_manifest_is_windows_architecture_bound():
    manifest = json.loads(
        (Path(__file__).parents[2] / "tools" / "bundled_uv.json").read_text(encoding="utf-8")
    )
    assert manifest["os"] == "windows"
    assert manifest["architecture"] == "x64"
    assert manifest["platform"] == "x86_64-pc-windows-msvc"


def test_frozen_install_uv_reports_bundled_without_running_pip(monkeypatch, tmp_path):
    bundled = tmp_path / "runtime" / "uv.exe"
    bundled.parent.mkdir(parents=True)
    bundled.write_bytes(b"uv")

    class FakeUVManager:
        def get_bundled_uv_path(self):
            return str(bundled)

        def _verify_uv_executable(self, path):
            return path == str(bundled)

    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr("src.core.uv_manager.UVManager", FakeUVManager)
    pip_run = MagicMock()
    monkeypatch.setattr("src.cli_parity.subprocess.run", pip_run)

    result = CliRunner().invoke(app, ["env", "install-uv"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["status"] == "bundled"
    pip_run.assert_not_called()


def test_cli_json_smoke_outputs_machine_readable_documents(tmp_path, monkeypatch):
    workspace = tmp_path / "workflows"
    workspace.mkdir()
    monkeypatch.setenv("MOZIKIT_WORKSPACE", str(workspace))

    runner = CliRunner()
    listed = runner.invoke(app, ["workflow", "list", "--json"])
    assert listed.exit_code == 0, listed.output
    assert json.loads(listed.stdout) == []

    workflow = workspace / "demo.json"
    workflow.write_text(
        json.dumps(
            {
                "workflow_id": "demo-id",
                "workflow_name": "demo",
                "nodes": [],
                "edges": [],
                "active": False,
                "triggers": [],
            }
        ),
        encoding="utf-8",
    )
    runtime = MagicMock()
    runtime.is_running.return_value = False
    monkeypatch.setattr("src.core.runtime_client.RuntimeClient", lambda: runtime)
    status = runner.invoke(app, ["workflow", "status", str(workflow), "--json"])
    assert status.exit_code == 0, status.output
    assert json.loads(status.stdout)["workflow_id"] == "demo-id"

    executor = MagicMock()
    executor.workflow_name = "demo"
    executor.nodes = []
    dispatcher_result = SimpleNamespace(report={"success": True, "duration_ms": 1})
    from src import cli as cli_module
    real_load_workflow = cli_module._load_workflow
    monkeypatch.setattr(
        "src.cli._load_workflow",
        lambda path, dispatcher, json_output=False: executor,
    )
    monkeypatch.setattr(
        "src.cli.WorkflowRunDispatcher.dispatch_executor",
        lambda *args, **kwargs: dispatcher_result,
    )
    run = runner.invoke(app, ["run", str(workflow), "--json"])
    assert run.exit_code == 0, run.output
    assert json.loads(run.stdout)["success"] is True

    monkeypatch.setattr(cli_module, "_load_workflow", real_load_workflow)
    missing = runner.invoke(app, ["run", str(workspace / "missing.json"), "--json"])
    assert missing.exit_code == 1
    assert json.loads(missing.stdout)["success"] is False

    missing_description = runner.invoke(
        app, ["workflow", "describe", str(workspace / "missing.json"), "--json"]
    )
    assert missing_description.exit_code == 1
    assert json.loads(missing_description.stdout)["success"] is False


def test_spec_defines_two_shared_directory_entrypoints():
    spec = Path(__file__).parents[2] / "Mozikit.spec"
    text = spec.read_text(encoding="utf-8")
    assert "MERGE(" in text
    assert 'name="MozikitDesktop"' in text
    assert 'name="mozikit"' in text
    assert "console=False" in text
    assert "console=True" in text
    assert "COLLECT(" in text
