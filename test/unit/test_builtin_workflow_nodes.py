import json

from src.core.builtin_node_executors import (
    DebugNativeExecutor,
    DirectoryMonitorNativeExecutor,
)
from src.core.node_registry import get_registry
from src.core.trigger_manager import TriggerManager
from src.core.trigger_registry import TriggerRegistry
from src.core.folder_watch_trigger import FolderWatchTrigger
from src.core.workflow_service import WorkflowService
from src.core.node_extension_registries import native_executors
from src.core.workflow_executor import WorkflowExecutor
from src.core.uv_manager import UVManager


def test_builtin_directory_monitor_and_debug_are_registered():
    registry = get_registry()

    monitor = registry.get_node("folder_watch")
    debug = registry.get_node("debug")

    assert monitor is not None
    assert monitor.config_schema["path"]["type"] == "path"
    assert monitor.output_schema["event"]["type"] == "object"
    assert debug is not None
    assert debug.input_schema["input"]["type"] == "any"
    assert registry.get_node("directory_monitor") is monitor


def test_disabled_persistent_sources_do_not_block_deactivation():
    document = {
        "triggers": [{"trigger_id": "old", "enabled": False}],
        "nodes": [
            {
                "node_type": "folder_watch",
                "config": {"enabled": False, "path": "C:/unused"},
            }
        ],
    }
    assert WorkflowService.has_persistent_sources(document) is False


def test_deactivation_is_allowed_when_all_sources_are_disabled(tmp_path):
    workflow = tmp_path / "workflows" / "disabled" / "workflow.json"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        json.dumps(
            {
                "workflow_id": "disabled-workflow",
                "workflow_name": "Disabled",
                "active": True,
                "triggers": [{"trigger_id": "old", "enabled": False}],
                "nodes": [
                    {
                        "node_id": "watch",
                        "node_type": "folder_watch",
                        "config": {"enabled": False, "path": str(tmp_path)},
                    }
                ],
                "edges": [],
            }
        ),
        encoding="utf-8",
    )

    service = WorkflowService(tmp_path / "workflows")
    document = service.set_active(str(workflow), False)
    assert document["active"] is False


def test_workflow_executor_restores_builtin_native_registrations(tmp_path):
    native_executors.clear()
    WorkflowExecutor("registration-check", UVManager(str(tmp_path)))
    assert native_executors.has("directory_monitor")
    assert native_executors.has("debug")


def test_native_nodes_route_an_event_to_debug():
    event = {
        "event_id": "event-1",
        "event_type": "created",
        "path": "/tmp/incoming.json",
        "filename": "incoming.json",
    }
    monitor_output = DirectoryMonitorNativeExecutor().execute(
        node=None, input_data=event, context={}
    )
    debug_output = DebugNativeExecutor().execute(
        node=None,
        input_data={"input": monitor_output["event"]},
        context={},
    )

    assert monitor_output["event"] == debug_output["value"]
    assert debug_output["value"]["event_type"] == "created"


def test_directory_monitor_node_is_an_implicit_runtime_source(tmp_path):
    root = tmp_path / "watch"
    root.mkdir()
    workflow = tmp_path / "workflows" / "demo" / "workflow.json"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        json.dumps(
            {
                "workflow_id": "workflow-1",
                "workflow_name": "Demo",
                "active": True,
                "triggers": [],
                "nodes": [
                    {
                        "node_id": "watch-node",
                        "node_type": "folder_watch",
                        "config": {"path": str(root), "settle_ms": 0},
                    }
                ],
                "edges": [],
            }
        ),
        encoding="utf-8",
    )

    registry = TriggerRegistry()
    registry.register("folder_watch", FolderWatchTrigger)
    manager = TriggerManager(tmp_path / "workflows", registry=registry)
    try:
        status = manager.reconcile()
        assert status["desired"] == ["workflow-1/watch-node"]
        assert status["actual"]["workflow-1/watch-node"]["entry_node_id"] == "watch-node"
    finally:
        manager.stop()
