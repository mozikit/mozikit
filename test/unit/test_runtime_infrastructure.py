"""Acceptance tests for persistent runtime extension infrastructure."""

import json
import sys
from pathlib import Path

import pytest

from src.core.node_base import CustomNode
from src.core.runtime_base import RuntimeBase
from src.core.runtime_manager import RuntimeManager, RuntimeService
from src.core.runtime_registry import RuntimeRegistry
from src.core.uv_manager import UVManager
from src.core.workflow_executor import WorkflowExecutor


PROJECT_ROOT = Path(__file__).resolve().parents[2]
ECHO_DEFINITION = PROJECT_ROOT / "examples" / "test_runtime" / "runtime.json"
RUNTIME_CALL_SOURCE = (
    PROJECT_ROOT / "examples" / "runtime_call_node" / "node.py"
).read_text(encoding="utf-8")


class TrackingRuntime(RuntimeBase):
    def __init__(self, runtime_id, config=None):
        super().__init__(runtime_id, config)
        self.started = False
        self.stopped = False

    def start(self):
        self.started = True

    def stop(self):
        self.stopped = True

    def call(self, action, params):
        return {"action": action, "params": params}


def test_runtime_registry_and_manager_lifecycle():
    registry = RuntimeRegistry()
    registry.register("tracking", TrackingRuntime)
    manager = RuntimeManager(registry)

    runtime = manager.start_runtime("tracking", "tracking-1", {"key": "value"})

    assert runtime.started is True
    assert manager.call("tracking-1", "ping", {"n": 1}) == {
        "action": "ping",
        "params": {"n": 1},
    }
    manager.stop_runtime("tracking-1")
    assert runtime.stopped is True
    assert "tracking-1" not in manager.instances


def test_runtime_definition_dynamically_imports_echo_runtime():
    registry = RuntimeRegistry()

    runtime_type = registry.load_definition(str(ECHO_DEFINITION))
    manager = RuntimeManager(registry)
    runtime = manager.start_runtime(runtime_type, "echo-1")

    assert manager.call("echo-1", "echo", {"text": "hello"}) == {"text": "hello"}
    manager.stop_all()
    assert runtime.started is False


def _runtime_call_workflow(name, uv_manager, service_url):
    executor = WorkflowExecutor(name, uv_manager=uv_manager)
    node = CustomNode(
        "runtime-call",
        "runtime_call",
        {
            "runtime_id": "echo-1",
            "action": "count",
            "params": {},
            "runtime_url": service_url,
        },
    )
    node.source_code = RUNTIME_CALL_SOURCE
    executor.add_node(node)
    return executor


def test_two_workflow_runs_share_runtime_state_and_stop_with_service(tmp_path, monkeypatch):
    """Each run gets a new worker process while EchoRuntime keeps its count."""
    registry = RuntimeRegistry()
    registry.load_definition(str(ECHO_DEFINITION))
    manager = RuntimeManager(registry)
    runtime = manager.start_runtime("echo", "echo-1")
    service = RuntimeService(manager, port=0)
    service.start()

    uv_manager = UVManager(workspace_root=str(tmp_path / "workflows"))
    monkeypatch.setattr(
        uv_manager,
        "_get_python_executable",
        lambda workflow_name: Path(sys.executable),
    )

    try:
        first = _runtime_call_workflow("run-1", uv_manager, service.base_url).execute(
            return_report=True
        )
        second = _runtime_call_workflow("run-2", uv_manager, service.base_url).execute(
            return_report=True
        )

        assert first["success"] is True, first
        assert first["final_context"]["count"] == 1
        assert second["success"] is True, second
        assert second["final_context"]["count"] == 2
        assert runtime.started is True
        assert service.manager.health("echo-1") == {"status": "running"}
    finally:
        service.stop()

    assert runtime.started is False
    assert manager.instances == {}


def test_runtime_http_service_rejects_unknown_runtime():
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    manager = RuntimeManager(RuntimeRegistry())
    service = RuntimeService(manager, port=0)
    service.start()
    request = Request(
        f"{service.base_url}/runtime/missing/call",
        data=json.dumps({"action": "echo", "params": {}}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with pytest.raises(HTTPError) as exc_info:
            urlopen(request, timeout=5)
        assert exc_info.value.code == 404
    finally:
        service.stop()
