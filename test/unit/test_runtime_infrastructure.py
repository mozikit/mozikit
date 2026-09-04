"""Acceptance tests for persistent runtime extension infrastructure."""

import json
import shutil
import sys
from pathlib import Path

import pytest

from src.core.node_base import CustomNode
from src.core.runtime_base import RuntimeBase
from src.core.runtime_host import RuntimeHost
from src.core.runtime_client import RuntimeClient
from src.core.runtime_daemon import RuntimeDaemon, RuntimeDaemonAlreadyRunning
from src.core.runtime_paths import get_runtime_dir
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


def _runtime_call_workflow(name, uv_manager, service_url=None, token=None):
    config = {
        "runtime_id": "echo-1",
        "action": "count",
        "params": {},
    }
    if service_url:
        config["runtime_url"] = service_url
    if token:
        config["runtime_token"] = token
    executor = WorkflowExecutor(name, uv_manager=uv_manager)
    node = CustomNode(
        "runtime-call",
        "runtime_call",
        config,
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
    service = RuntimeService(manager, port=0, auth_token="test-token")
    service.start()

    uv_manager = UVManager(workspace_root=str(tmp_path / "workflows"))
    monkeypatch.setattr(
        uv_manager,
        "_get_python_executable",
        lambda workflow_name: Path(sys.executable),
    )

    try:
        first = _runtime_call_workflow(
            "run-1", uv_manager, service.base_url, "test-token"
        ).execute(
            return_report=True
        )
        second = _runtime_call_workflow(
            "run-2", uv_manager, service.base_url, "test-token"
        ).execute(
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

    # RuntimeService owns only HTTP transport; RuntimeManager owns instances.
    assert runtime.started is True
    assert "echo-1" in manager.instances
    manager.stop_all()
    assert runtime.started is False
    assert manager.instances == {}


def test_runtime_host_loads_config_and_persists_across_workflow_runs(
    tmp_path, monkeypatch
):
    config_path = tmp_path / "runtimes.json"
    config_path.write_text(
        json.dumps(
            {
                "runtime_type": "echo",
                "runtime_id": "echo-1",
                "enabled": True,
                "config": {},
            }
        ),
        encoding="utf-8",
    )
    registry = RuntimeRegistry()
    host = RuntimeHost(
        config_path=str(config_path),
        plugin_root=str(ECHO_DEFINITION.parent),
        registry=registry,
        port=0,
        auth_token="test-token",
    )
    host.start()
    runtime = host.manager.instances["echo-1"]

    uv_manager = UVManager(workspace_root=str(tmp_path / "workflows"))
    monkeypatch.setattr(
        uv_manager,
        "_get_python_executable",
        lambda workflow_name: Path(sys.executable),
    )

    try:
        first = _runtime_call_workflow(
            "host-run-1", uv_manager, host.base_url, "test-token"
        ).execute(return_report=True)
        second = _runtime_call_workflow(
            "host-run-2", uv_manager, host.base_url, "test-token"
        ).execute(return_report=True)

        assert first["success"] is True, first
        assert first["final_context"]["count"] == 1
        assert second["success"] is True, second
        assert second["final_context"]["count"] == 2
        assert host.is_running is True
        assert runtime.started is True
    finally:
        host.stop()

    assert host.is_running is False
    assert runtime.started is False
    assert host.manager.instances == {}


def test_runtime_http_service_rejects_unknown_runtime():
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    manager = RuntimeManager(RuntimeRegistry())
    service = RuntimeService(manager, port=0, auth_token="test-token")
    service.start()
    request = Request(
        f"{service.base_url}/runtime/missing/call",
        data=json.dumps({"action": "echo", "params": {}}).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer test-token",
        },
        method="POST",
    )
    try:
        with pytest.raises(HTTPError) as exc_info:
            urlopen(request, timeout=5)
        assert exc_info.value.code == 404
    finally:
        service.stop()


def test_runtime_service_requires_bearer_token():
    from urllib.error import HTTPError
    from urllib.request import Request, urlopen

    service = RuntimeService(
        RuntimeManager(RuntimeRegistry()), port=0, auth_token="secret"
    )
    service.start()
    try:
        with pytest.raises(HTTPError) as exc_info:
            urlopen(Request(f"{service.base_url}/health"), timeout=5)
        assert exc_info.value.code == 401
    finally:
        service.stop()


def test_runtime_daemon_is_single_owner_and_injects_worker_connection(
    tmp_path, monkeypatch
):
    runtime_dir = tmp_path / "app-data" / "runtime"
    plugin_dir = runtime_dir / "plugins" / "echo"
    plugin_dir.mkdir(parents=True)
    shutil.copy2(ECHO_DEFINITION, plugin_dir / "runtime.json")
    shutil.copy2(ECHO_DEFINITION.parent / "runtime.py", plugin_dir / "runtime.py")
    (runtime_dir / "runtimes.json").write_text(
        json.dumps(
            {
                "runtime_type": "echo",
                "runtime_id": "echo-1",
                "enabled": True,
                "config": {},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("MOZIKIT_APP_DATA_DIR", str(runtime_dir.parent))

    daemon = RuntimeDaemon(runtime_dir=runtime_dir, port=0)
    daemon.start()
    second_daemon = RuntimeDaemon(runtime_dir=runtime_dir, port=0)
    with pytest.raises(RuntimeDaemonAlreadyRunning):
        second_daemon.start()

    client = RuntimeClient(runtime_dir)
    assert client.is_running() is True
    uv_manager = UVManager(workspace_root=str(tmp_path / "workflows"))
    monkeypatch.setattr(
        uv_manager,
        "_get_python_executable",
        lambda workflow_name: Path(sys.executable),
    )
    runtime = daemon.host.manager.instances["echo-1"]
    try:
        first = _runtime_call_workflow("daemon-run-1", uv_manager).execute(
            return_report=True
        )
        second = _runtime_call_workflow("daemon-run-2", uv_manager).execute(
            return_report=True
        )
        assert first["final_context"]["count"] == 1
        assert second["final_context"]["count"] == 2
        assert runtime.started is True
    finally:
        daemon.stop()

    assert runtime.started is False
    assert client.is_running() is False


def test_runtime_directory_is_independent_from_current_working_directory(
    tmp_path, monkeypatch
):
    app_data = tmp_path / "app-data"
    monkeypatch.setenv("MOZIKIT_APP_DATA_DIR", str(app_data))
    first = get_runtime_dir()
    other_cwd = tmp_path / "other-cwd"
    other_cwd.mkdir()
    monkeypatch.chdir(other_cwd)
    assert get_runtime_dir() == first == app_data / "runtime"
