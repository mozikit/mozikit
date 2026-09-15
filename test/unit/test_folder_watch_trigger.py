import json
import time

import pytest
from typer.testing import CliRunner

from src.cli import app
from src.core.folder_watch_trigger import FolderWatchTrigger
from src.core.trigger_manager import TriggerManager
from src.core.trigger_registry import TriggerRegistry
from src.core.workflow_executor import WorkflowExecutor
from src.core.workflow_service import WorkflowService


def wait_for(predicate, timeout=3):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        time.sleep(0.02)
    return predicate()


def test_folder_watch_filters_recursive_and_stops(tmp_path):
    root = tmp_path / "watch"
    root.mkdir()
    events = []
    trigger = FolderWatchTrigger("watch", {"path": "~", "include": ["*.sav"], "exclude": ["*.tmp"], "settle_ms": 0, "debounce_ms": 100})
    trigger.config["path"] = str(root)
    trigger.start(events.append)
    try:
        child = root / "sub"
        child.mkdir()
        target = child / "save.sav"
        target.write_text("a")
        assert wait_for(lambda: any(item["event_type"] == "created" for item in events))
        assert all(item["filename"].endswith(".sav") for item in events)
        target.write_text("b")
        assert wait_for(lambda: any(item["event_type"] == "modified" for item in events))
        target.rename(child / "renamed.sav")
        assert wait_for(lambda: any(item["event_type"] == "moved" for item in events))
        (child / "renamed.sav").unlink()
        assert wait_for(lambda: any(item["event_type"] == "deleted" for item in events))
        count = len(events)
    finally:
        trigger.stop()
    (root / "after.sav").write_text("ignored")
    time.sleep(0.15)
    assert len(events) == count
    assert trigger.is_running is False


def test_folder_watch_debounce_reduces_repeated_events(tmp_path):
    events = []
    trigger = FolderWatchTrigger("watch", {"path": str(tmp_path), "events": ["modified"], "settle_ms": 0, "debounce_ms": 250})
    trigger.start(events.append)
    try:
        target = tmp_path / "save.sav"
        target.write_text("a")
        for value in range(4):
            target.write_text(str(value))
        assert wait_for(lambda: events)
        time.sleep(0.35)
        assert len([event for event in events if event["event_type"] == "modified"]) <= 2
    finally:
        trigger.stop()


def test_inactive_workflow_does_not_start_folder_watch(tmp_path):
    root = tmp_path / "watch"
    root.mkdir()
    workflow = tmp_path / "workflows" / "demo" / "workflow.json"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(json.dumps({"workflow_id": "wf", "workflow_name": "Demo", "active": False, "triggers": [{"trigger_id": "files", "trigger_type": "folder_watch", "config": {"path": str(root)}}]}))
    registry = TriggerRegistry()
    registry.register("folder_watch", FolderWatchTrigger)
    manager = TriggerManager(tmp_path / "workflows", registry=registry)
    try:
        assert manager.reconcile()["actual"] == {}
        manager.activate_workflow(str(workflow))
        assert wait_for(lambda: "wf/files" in manager.status()["actual"])
        manager.deactivate_workflow("wf")
        assert manager.status()["actual"] == {}
    finally:
        manager.stop()


def test_active_invalid_folder_watch_reports_runtime_error(tmp_path):
    workflow = tmp_path / "workflows" / "demo" / "workflow.json"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        json.dumps(
            {
                "workflow_id": "wf",
                "workflow_name": "Demo",
                "active": True,
                "triggers": [
                    {
                        "trigger_id": "files",
                        "trigger_type": "folder_watch",
                        "enabled": True,
                        "config": {"path": str(tmp_path / "missing")},
                    }
                ],
            }
        )
    )
    registry = TriggerRegistry()
    registry.register("folder_watch", FolderWatchTrigger)
    manager = TriggerManager(tmp_path / "workflows", registry=registry)
    try:
        status = manager.reconcile()
        assert status["actual"] == {}
        assert "wf/files" in status["errors"]
        assert "does not exist" in status["errors"]["wf/files"]
    finally:
        manager.stop()


def test_cli_trigger_management_and_json_status(tmp_path, monkeypatch):
    monkeypatch.setenv("MOZIKIT_WORKSPACE", str(tmp_path))
    workflow = tmp_path / "demo" / "workflow.json"
    workflow.parent.mkdir()
    workflow.write_text(json.dumps({"workflow_id": "wf", "workflow_name": "Demo", "active": False, "triggers": [], "nodes": [], "edges": []}))
    runner = CliRunner()
    added = runner.invoke(app, ["workflow", "trigger", "add", "demo", "folder_watch", "--id", "files", "--path", str(tmp_path)])
    assert added.exit_code == 0, added.output
    assert runner.invoke(app, ["workflow", "trigger", "disable", "demo", "files"]).exit_code == 0
    listed = runner.invoke(app, ["workflow", "trigger", "list", "demo", "--json"])
    assert listed.exit_code == 0
    assert json.loads(listed.output)[0]["enabled"] is False
    assert runner.invoke(app, ["workflow", "trigger", "enable", "demo", "files"]).exit_code == 0
    status = runner.invoke(app, ["workflow", "status", "demo", "--json"])
    assert status.exit_code == 0
    assert json.loads(status.output)["workflow_id"] == "wf"
    assert runner.invoke(app, ["workflow", "trigger", "remove", "demo", "files"]).exit_code == 0


def test_trigger_crud_uses_ids_and_partial_update_preserves_config(tmp_path):
    workflow = tmp_path / "demo" / "workflow.json"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        json.dumps(
            {
                "workflow_id": "wf",
                "workflow_name": "Demo",
                "active": False,
                "triggers": [],
                "nodes": [],
                "edges": [],
            }
        )
    )
    service = WorkflowService(tmp_path)
    original = service.add_trigger(
        "demo",
        "folder_watch",
        "files",
        {"path": str(tmp_path), "include": ["*.sav"]},
    )
    assert original["config"]["include"] == ["*.sav"]
    assert service.get_trigger("demo", "files")["trigger_id"] == "files"

    updated = service.update_trigger(
        "demo", "files", config={"debounce_ms": 1000}
    )
    assert updated["config"]["path"] == str(tmp_path)
    assert updated["config"]["debounce_ms"] == 1000
    assert service.disable_trigger("demo", "files")["enabled"] is False
    assert service.enable_trigger("demo", "files")["enabled"] is True

    with pytest.raises(ValueError, match="duplicate"):
        service.add_trigger("demo", "folder_watch", "files", {"path": str(tmp_path)})
    with pytest.raises(KeyError, match="does not exist"):
        service.get_trigger("demo", "missing")
    with pytest.raises(ValueError, match="unknown trigger"):
        service.add_trigger("demo", "missing_type", "other", {})

    model = WorkflowExecutor("Demo")
    model.triggers = service.list_triggers("demo")
    WorkflowService.update_trigger_model(
        model, "files", config={"settle_ms": 123}, enabled=False
    )
    assert model.triggers[0]["config"]["settle_ms"] == 123
    assert model.triggers[0]["enabled"] is False
    assert model.nodes == {}


def test_cli_trigger_set_and_show_are_json_safe(tmp_path, monkeypatch):
    monkeypatch.setenv("MOZIKIT_WORKSPACE", str(tmp_path))
    workflow = tmp_path / "demo" / "workflow.json"
    workflow.parent.mkdir()
    workflow.write_text(
        json.dumps(
            {
                "workflow_id": "wf",
                "workflow_name": "Demo",
                "active": False,
                "triggers": [
                    {
                        "trigger_id": "files",
                        "trigger_type": "folder_watch",
                        "enabled": True,
                        "config": {"path": "D:/Games/A", "debounce_ms": 400},
                    }
                ],
                "nodes": [],
                "edges": [],
            }
        )
    )
    runner = CliRunner()
    changed = runner.invoke(
        app,
        ["workflow", "trigger", "set", "demo", "files", "--path", "D:/Games/B", "--debounce", "1000"],
    )
    assert changed.exit_code == 0, changed.output
    shown = runner.invoke(
        app, ["workflow", "trigger", "show", "demo", "files", "--json"]
    )
    assert shown.exit_code == 0, shown.output
    data = json.loads(shown.output)
    assert data["config"]["path"] == "D:/Games/B"
    assert data["config"]["debounce_ms"] == 1000
