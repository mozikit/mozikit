"""Persistent trigger desired/actual reconciliation tests."""

import json
import sys
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

from src.core.trigger_base import TriggerBase
from src.core.trigger_manager import TriggerManager
from src.core.trigger_registry import TriggerRegistry
from src.core.test_trigger import TestTrigger
from src.core.runtime_client import RuntimeClient
from src.core.runtime_daemon import RuntimeDaemon
from src.core.config_manager import ConfigManager
from src.core.node_base import CustomNode
from src.core.uv_manager import UVManager
from src.core.workflow_executor import WorkflowExecutor
from src.core.workflow_run_dispatcher import WorkflowRunDispatcher


class ManualTrigger(TriggerBase):
    instances = []

    def __init__(self, trigger_id, config=None):
        super().__init__(trigger_id, config)
        self.emit = None
        self.is_running = False
        self.stop_calls = 0
        self.__class__.instances.append(self)

    def start(self, emit):
        self.emit = emit
        self.is_running = True

    def stop(self):
        self.stop_calls += 1
        self.is_running = False


class RecordingDispatcher:
    def __init__(self):
        self.calls = []
        self.called = threading.Event()

    def run(self, workflow_path, **kwargs):
        self.calls.append((workflow_path, kwargs))
        self.called.set()
        return {"success": True}


def _write_workflow(path: Path, *, active=True, interval=1, trigger_type="manual"):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "workflow_id": "workflow-a",
                "workflow_name": "Workflow A",
                "active": active,
                "triggers": [
                    {
                        "trigger_id": "test-trigger",
                        "trigger_type": trigger_type,
                        "config": {"interval": interval},
                    }
                ],
                "nodes": [],
                "edges": [],
            }
        ),
        encoding="utf-8",
    )


def _manager(tmp_path, dispatcher=None):
    registry = TriggerRegistry()
    registry.register("manual", ManualTrigger)
    return TriggerManager(
        tmp_path / "workflows",
        registry=registry,
        dispatcher=dispatcher or RecordingDispatcher(),
        state_path=tmp_path / "trigger-state.json",
        reconcile_interval=0.05,
    )


def test_reconcile_tracks_activation_config_change_and_deletion(tmp_path):
    ManualTrigger.instances.clear()
    workflow_path = tmp_path / "workflows" / "a" / "workflow.json"
    _write_workflow(workflow_path)
    manager = _manager(tmp_path)
    try:
        status = manager.reconcile()
        assert status["desired"] == ["workflow-a/test-trigger"]
        assert status["actual"]["workflow-a/test-trigger"]["status"] == "running"
        first = ManualTrigger.instances[-1]

        _write_workflow(workflow_path, interval=2)
        manager.reconcile()
        assert first.stop_calls == 1
        assert ManualTrigger.instances[-1] is not first

        manager.deactivate_workflow("workflow-a")
        assert manager.status()["actual"] == {}

        manager.activate_workflow(str(workflow_path))
        assert "workflow-a/test-trigger" in manager.status()["actual"]
        workflow_path.unlink()
        manager.reconcile()
        assert manager.status()["actual"] == {}
    finally:
        manager.stop()


def test_emit_dispatches_independent_run_and_deduplicates(tmp_path):
    ManualTrigger.instances.clear()
    workflow_path = tmp_path / "workflows" / "a" / "workflow.json"
    _write_workflow(workflow_path)
    dispatcher = RecordingDispatcher()
    manager = _manager(tmp_path, dispatcher)
    try:
        manager.reconcile()
        trigger = ManualTrigger.instances[-1]
        event = {"event_id": "message-1", "text": "hello"}
        trigger.emit(event)
        assert dispatcher.called.wait(2)
        trigger.emit(event)
        time.sleep(0.1)

        assert len(dispatcher.calls) == 1
        path, kwargs = dispatcher.calls[0]
        assert path == str(workflow_path)
        assert kwargs["trigger_type"] == "trigger"
        assert kwargs["initial_data"] == event
    finally:
        manager.stop()


def test_restart_recovers_active_trigger_and_persistent_dedupe(tmp_path):
    ManualTrigger.instances.clear()
    workflow_path = tmp_path / "workflows" / "a" / "workflow.json"
    _write_workflow(workflow_path)
    first_dispatcher = RecordingDispatcher()
    first = _manager(tmp_path, first_dispatcher)
    first.reconcile()
    ManualTrigger.instances[-1].emit({"event_id": "same"})
    assert first_dispatcher.called.wait(2)
    first.stop()

    second_dispatcher = RecordingDispatcher()
    second = _manager(tmp_path, second_dispatcher)
    try:
        second.reconcile()
        assert "workflow-a/test-trigger" in second.status()["actual"]
        ManualTrigger.instances[-1].emit({"event_id": "same"})
        time.sleep(0.1)
        assert second_dispatcher.calls == []
    finally:
        second.stop()


def test_reconcile_restarts_crashed_trigger(tmp_path):
    ManualTrigger.instances.clear()
    workflow_path = tmp_path / "workflows" / "a" / "workflow.json"
    _write_workflow(workflow_path)
    manager = _manager(tmp_path)
    try:
        manager.reconcile()
        crashed = ManualTrigger.instances[-1]
        crashed.is_running = False
        manager.reconcile()
        assert crashed.stop_calls == 1
        assert ManualTrigger.instances[-1] is not crashed
    finally:
        manager.stop()


def test_test_trigger_emits_sequences_and_stops():
    events = []
    received = threading.Event()
    trigger = TestTrigger("ticker", {"interval": 0.01})

    def emit(payload):
        events.append(payload)
        if len(events) >= 2:
            received.set()

    trigger.start(emit)
    assert received.wait(1)
    trigger.stop()
    count_after_stop = len(events)
    time.sleep(0.03)

    assert [event["sequence"] for event in events[:2]] == [1, 2]
    assert len(events) == count_after_stop
    assert trigger.is_running is False


def test_active_trigger_workflow_configures_runtime_client(tmp_path, monkeypatch):
    workspace = tmp_path / "workflows"
    workflow_path = workspace / "a" / "workflow.json"
    _write_workflow(workflow_path)
    monkeypatch.setenv("MOZIKIT_WORKSPACE", str(workspace))

    assert RuntimeClient(tmp_path / "runtime").is_configured() is True

    _write_workflow(workflow_path, active=False)
    assert RuntimeClient(tmp_path / "runtime").is_configured() is False


def test_workflow_round_trip_preserves_trigger_activation(tmp_path):
    path = tmp_path / "workflow.json"
    executor = WorkflowExecutor("trigger-workflow")
    executor.workflow_id = "stable-id"
    executor.active = True
    executor.triggers = [
        {"trigger_id": "ticker", "trigger_type": "test", "config": {"interval": 1}}
    ]
    executor.save_workflow(str(path))

    loaded = WorkflowExecutor.load_workflow(str(path))
    assert loaded.workflow_id == "stable-id"
    assert loaded.active is True
    assert loaded.triggers == executor.triggers


def test_trigger_event_runs_an_independent_workflow_worker(tmp_path):
    ManualTrigger.instances.clear()
    workflow_path = tmp_path / "workflows" / "a" / "workflow.json"
    _write_workflow(workflow_path)
    uv_manager = UVManager(workspace_root=str(tmp_path / "worker-data"))
    uv_manager.create_workflow_env = lambda *args, **kwargs: True
    uv_manager._get_python_executable = lambda workflow_name: Path(sys.executable)
    config_manager = ConfigManager(str(tmp_path / "config.json"))
    config_manager.save_config = config_manager.save_config_sync
    runtime_client = MagicMock()

    class RealDispatcher(WorkflowRunDispatcher):
        def run(self, path, **kwargs):
            executor = WorkflowExecutor("event-workflow", uv_manager)
            node = CustomNode("capture", "capture_event", {})
            node.source_code = (
                "def execute(self, input_data):\n"
                "    return {'captured_sequence': input_data['sequence']}\n"
            )
            executor.add_node(node)
            return self.dispatch_executor(
                executor,
                workflow_path=path,
                trigger_type=kwargs["trigger_type"],
                initial_data=kwargs["initial_data"],
            ).report

    dispatcher = RealDispatcher(config_manager, runtime_client)
    manager = _manager(tmp_path, dispatcher)
    try:
        manager.reconcile()
        ManualTrigger.instances[-1].emit({"event_id": "run-1", "sequence": 7})
        deadline = time.monotonic() + 5
        while not config_manager.get_execution_history() and time.monotonic() < deadline:
            time.sleep(0.05)

        history = config_manager.get_execution_history()
        assert len(history) == 1
        assert history[0]["status"] == "success"
        assert history[0]["output"]["captured_sequence"] == 7
        runtime_client.ensure_running.assert_called_once_with()
    finally:
        manager.stop()


def test_runtime_daemon_owns_trigger_and_restores_it_after_restart(
    tmp_path, monkeypatch
):
    workspace = tmp_path / "workflows"
    _write_workflow(
        workspace / "a" / "workflow.json",
        interval=60,
        trigger_type="test",
    )
    monkeypatch.setenv("MOZIKIT_WORKSPACE", str(workspace))
    runtime_dir = tmp_path / "runtime"

    first = RuntimeDaemon(runtime_dir=runtime_dir, port=0)
    first.start()
    try:
        assert "workflow-a/test-trigger" in first.host.trigger_manager.status()["actual"]
        client_status = RuntimeClient(runtime_dir).trigger_status()
        assert "workflow-a/test-trigger" in client_status["actual"]
    finally:
        first.stop()

    second = RuntimeDaemon(runtime_dir=runtime_dir, port=0)
    second.start()
    try:
        assert "workflow-a/test-trigger" in second.host.trigger_manager.status()["actual"]
    finally:
        second.stop()


def test_runtime_client_rejects_daemon_for_another_workspace(tmp_path, monkeypatch):
    first_workspace = tmp_path / "first"
    second_workspace = tmp_path / "second"
    first_workspace.mkdir()
    second_workspace.mkdir()
    runtime_dir = tmp_path / "runtime"
    monkeypatch.setenv("MOZIKIT_WORKSPACE", str(first_workspace))
    daemon = RuntimeDaemon(runtime_dir=runtime_dir, port=0)
    daemon.start()
    try:
        client = RuntimeClient(runtime_dir)
        assert client.is_running() is True
        monkeypatch.setenv("MOZIKIT_WORKSPACE", str(second_workspace))
        assert client.is_alive() is True
        assert client.is_running() is False
    finally:
        daemon.stop()


def test_trigger_manager_can_restart_after_stop(tmp_path):
    ManualTrigger.instances.clear()
    _write_workflow(tmp_path / "workflows" / "a" / "workflow.json")
    manager = _manager(tmp_path)

    manager.start()
    manager.stop()
    manager.start()
    try:
        assert "workflow-a/test-trigger" in manager.status()["actual"]
    finally:
        manager.stop()
