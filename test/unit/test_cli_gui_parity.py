"""Behavioral contracts shared by the Qt frontend and CLI."""
import json
import signal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from src.cli import app
from src.core.config_manager import ConfigManager
from src.core.node_registry import NodeDefinition, NodeSource
from src.core.workflow_executor import WorkflowExecutor
from src.core.workflow_run_dispatcher import WorkflowRunDispatcher


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MOZIKIT_WORKSPACE", str(tmp_path))
    manager = ConfigManager(tmp_path / "config.json")
    for module in ("src.cli", "src.cli_parity", "src.core.config_manager"):
        monkeypatch.setattr(module + ".ConfigManager", lambda *args, **kwargs: manager)
    registry = MagicMock()
    definition = NodeDefinition("demo", "Demo", "", NodeSource.CUSTOM, "", "", {},
                                input_schema={"input": {"type": "any"}},
                                output_schema={"output": {"type": "any"}})
    registry.get_node.return_value = definition
    registry.build_default_config.return_value = {}
    for module in ("src.cli", "src.cli_parity", "src.core.node_registry"):
        monkeypatch.setattr(module + ".get_registry", lambda: registry)
    return manager, registry, definition


def write_workflow(tmp_path, nodes=None, edges=None):
    path = tmp_path / "workflow.json"
    document = {"version": 2, "workflow_name": "demo", "workflow_id": "stable-id",
                "active": False, "triggers": [], "nodes": nodes or [
                    {"node_id": name, "node_type": "demo", "config": {},
                     "position": {"x": index * 100, "y": 50}}
                    for index, name in enumerate(["a", "b", "c"])],
                "edges": edges or [], "canvas_state": {"scale_x": 1.3, "offset_y": 22}}
    path.write_text(json.dumps(document), encoding="utf-8")
    return path, document


def invoke(*args):
    result = CliRunner().invoke(app, list(map(str, args)))
    assert result.exit_code == 0, (result.output, result.exception)
    return result


def test_config_roundtrip_keeps_types_positions_and_view(isolated, tmp_path):
    path, original = write_workflow(tmp_path)
    invoke("workflow", "update-node", path, "a", "enabled=false", "timeout=30",
           'values=[1,2]', 'options={"x":true}', 'text="30"')
    document = json.loads(path.read_text(encoding="utf-8"))
    assert document["nodes"][0]["config"] == {
        "enabled": False, "timeout": 30, "values": [1, 2], "options": {"x": True}, "text": "30"}
    assert document["canvas_state"] == original["canvas_state"]
    assert document["workflow_id"] == original["workflow_id"]
    assert [n["position"] for n in document["nodes"]] == [n["position"] for n in original["nodes"]]


def test_connect_replaces_old_edge_and_rejects_invalid_ports(isolated, tmp_path):
    path, original = write_workflow(tmp_path, edges=[
        {"from_node": "a", "from_port": "output", "to_node": "c", "to_port": "input"}])
    invoke("workflow", "connect", path, "b", "c")
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert doc["edges"] == [{"from_node": "b", "from_port": "output", "to_node": "c", "to_port": "input"}]
    assert doc["nodes"][0]["outputs"] == []
    assert doc["canvas_state"] == original["canvas_state"]
    before = path.read_bytes()
    for args in [("c", "c"), ("a", "c", "--from-port", "missing")]:
        assert CliRunner().invoke(app, ["workflow", "connect", str(path), *args]).exit_code != 0
        assert path.read_bytes() == before
    isolated[2].input_schema = {"input": {"type": "object"}}
    isolated[2].output_schema = {"output": {"type": "string"}}
    assert CliRunner().invoke(app, ["workflow", "connect", str(path), "a", "c"]).exit_code != 0
    assert path.read_bytes() == before


def test_credentials_use_store_and_never_echo_secret(isolated, monkeypatch, tmp_path):
    manager, _, _ = isolated
    store, delete = MagicMock(return_value="protected-reference"), MagicMock()
    monkeypatch.setattr("src.core.custom_credentials.store_credential", store)
    monkeypatch.setattr("src.core.custom_credentials.delete_credential", delete)
    result = invoke("config", "set", "custom_credentials.demo", "SAMPLE-SECRET")
    assert "SAMPLE-SECRET" not in result.output
    store.assert_called_once_with("demo", "SAMPLE-SECRET")
    assert manager.config["custom_credentials"]["demo"] == "protected-reference"
    assert "SAMPLE-SECRET" not in manager.config_file.read_text(encoding="utf-8")
    # Also mask old plaintext values left by previous CLI versions.
    manager.config["custom_credentials"]["legacy"] = "OLD-SECRET"
    for args in [("config", "show"), ("config", "get", "custom_credentials"),
                 ("config", "get", "custom_credentials.legacy"), ("credential", "list")]:
        assert "OLD-SECRET" not in invoke(*args).output
    invoke("config", "unset", "custom_credentials.demo")
    delete.assert_called_once_with("demo")
    assert "demo" not in manager.config["custom_credentials"]
    file = tmp_path / "value.txt"
    file.write_text("FILE-SECRET\n", encoding="utf-8")
    assert "FILE-SECRET" not in invoke("credential", "set", "file", "--value-file", file).output
    assert CliRunner().invoke(app, ["config", "set", "custom_credentials.github_token", "x"]).exit_code != 0


def test_dispatch_target_includes_upstream_and_no_siblings():
    executor = MagicMock()
    executor.nodes = dict.fromkeys(["a", "b", "c", "d"])
    executor.edges = [SimpleNamespace(from_node=a, to_node=b) for a, b in [("a", "b"), ("b", "c"), ("a", "d")]]
    executor.execute.return_value = {"success": True, "run_id": "run"}
    executor.build_execution_record.return_value = {"id": "run"}
    dispatcher = WorkflowRunDispatcher(MagicMock(), MagicMock())
    dispatcher.dispatch_executor(executor, workflow_path="demo.json", trigger_type="cli", target_node_id="c")
    assert executor.prepare_environment.call_args.kwargs["node_ids"] == {"a", "b", "c"}
    assert executor.execute.call_args.kwargs["included_node_ids"] == {"a", "b", "c"}


def test_sigint_requests_stop_and_restores_handler():
    from src.core.execution_signals import stop_on_interrupt
    executor = MagicMock()
    original = signal.getsignal(signal.SIGINT)
    with stop_on_interrupt(executor, True):
        signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
    executor.request_stop.assert_called_once()
    assert signal.getsignal(signal.SIGINT) == original


def test_scripts_sync_schema_and_do_not_write_invalid_source(isolated, tmp_path):
    isolated[2].metadata = {"node_kind": "playwright_script"}
    path, original = write_workflow(tmp_path)
    script = tmp_path / "script.py"
    script.write_text('print("{{name}}")', encoding="utf-8")
    invoke("workflow", "script", "set", path, "a", script)
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert "name" in doc["nodes"][0]["config"]["param_schema"]
    assert doc["canvas_state"] == original["canvas_state"]
    invoke("workflow", "update-node", path, "a", "name=Alice")
    invoke("workflow", "script", "rescan", path, "a")
    assert json.loads(path.read_text(encoding="utf-8"))["nodes"][0]["config"]["name"] == "Alice"
    before = path.read_bytes()
    script.write_text("def broken(", encoding="utf-8")
    assert CliRunner().invoke(app, ["workflow", "script", "set", str(path), "a", str(script)]).exit_code != 0
    assert path.read_bytes() == before
    invoke("workflow", "script", "clear", path, "a")
    config = json.loads(path.read_text(encoding="utf-8"))["nodes"][0]["config"]
    assert "name" not in config and "name" not in config["param_schema"]
    assert config["script_source"] == ""
    assert CliRunner().invoke(app, ["workflow", "script", "validate", str(path), "a"]).exit_code != 0


def test_history_uses_common_index_and_reads_report(isolated, tmp_path):
    manager, _, _ = isolated
    artifacts = tmp_path / "run-id"
    artifacts.mkdir()
    report = {"run_id": "run-id", "nodes": [{"output": "x" * 200}]}
    (artifacts / "run.json").write_text(json.dumps(report), encoding="utf-8")
    manager.config["execution_history"] = [{"id": "short", "artifact_dir": str(artifacts), "workflow_name": "demo"}]
    assert json.loads(invoke("workflow", "history", "show", "short").output) == report
    assert json.loads(invoke("workflow", "history", "list", "--workflow", "missing").output) == []


def test_github_import_update_and_remove_use_provider(isolated, monkeypatch):
    _, registry, definition = isolated
    definition.source = NodeSource.GITHUB
    definition.repo_url = "https://github.com/example/nodes"
    registry.get_nodes_by_source.return_value = [definition]
    provider = MagicMock()
    provider.download_nodes.return_value = [definition]
    monkeypatch.setattr("src.cli_parity._github_provider", lambda: provider)
    invoke("node", "github", "import", definition.repo_url)
    invoke("node", "github", "update")
    assert provider.download_nodes.call_count == 2
    invoke("node", "github", "remove", definition.repo_url)
    provider.delete_node.assert_called_once_with("demo")
    registry.unregister_node.assert_called_once_with("demo")


def test_ai_connection_uses_saved_settings_and_reports_failure(isolated, monkeypatch):
    probe = MagicMock(return_value=(False, "认证失败"))
    monkeypatch.setattr("src.core.ai_connection.check_ai_connection", probe)
    isolated[0].config["ai_settings"] = {"model": "test"}
    result = CliRunner().invoke(app, ["config", "test-ai"])
    assert result.exit_code == 1
    assert json.loads(result.output)["success"] is False
    assert probe.call_args.args[2] == "test"


def test_uv_path_persists_after_validation(isolated, monkeypatch, tmp_path):
    from src.core.uv_manager import UVManager
    executable = tmp_path / "uv.exe"
    executable.touch()
    monkeypatch.setattr(UVManager, "_verify_uv_executable", lambda self, path: True)
    invoke("env", "set-uv-path", executable)
    assert UVManager().custom_uv_path == str(executable.resolve())
    monkeypatch.setattr(UVManager, "_verify_uv_executable", lambda self, path: False)
    assert CliRunner().invoke(app, ["env", "set-uv-path", str(executable)]).exit_code != 0


def test_source_commands_validate_before_writing(isolated, monkeypatch, tmp_path):
    from src.core.node_registry import NodeRegistry
    registry = NodeRegistry.__new__(NodeRegistry)
    registry._user_data_dir = tmp_path
    definition = isolated[2]
    definition.source = NodeSource.OFFICIAL
    definition.source_code = "original = True"
    registry._nodes = {"demo": definition}
    monkeypatch.setattr("src.cli_parity.get_registry", lambda: registry)
    code = tmp_path / "node.py"
    code.write_text("updated = True", encoding="utf-8")
    invoke("node", "source", "set", "demo", code)
    saved = tmp_path / "modified_nodes" / "demo.py"
    assert saved.read_text(encoding="utf-8") == "updated = True"
    code.write_text("def broken(", encoding="utf-8")
    assert CliRunner().invoke(app, ["node", "source", "set", "demo", str(code)]).exit_code != 0
    assert saved.read_text(encoding="utf-8") == "updated = True"
    assert invoke("node", "source", "show", "demo").output.strip() == "updated = True"


def test_record_saves_only_successful_codegen(isolated, monkeypatch, tmp_path):
    import subprocess
    isolated[2].metadata = {"node_kind": "playwright_script"}
    path, _ = write_workflow(tmp_path)
    before = path.read_bytes()
    def failure(command, **kwargs):
        raise subprocess.CalledProcessError(1, command)
    monkeypatch.setattr("src.cli_parity.subprocess.run", failure)
    assert CliRunner().invoke(app, ["workflow", "script", "record", str(path), "a"]).exit_code != 0
    assert path.read_bytes() == before
    def recorded(command, **kwargs):
        Path(command[command.index("-o") + 1]).write_text('print("{{url}}")', encoding="utf-8")
    monkeypatch.setattr("src.cli_parity.subprocess.run", recorded)
    invoke("workflow", "script", "record", path, "a", "--url", "https://example.test")
    assert "url" in json.loads(path.read_text(encoding="utf-8"))["nodes"][0]["config"]["param_schema"]


def test_cli_run_returns_full_report_and_output_together(isolated, monkeypatch, tmp_path):
    executor = MagicMock()
    executor.workflow_name = "demo"
    executor.nodes = {"a": MagicMock()}
    executor.edges = []
    report = {"success": True, "nodes": [{"output": {"long": "x" * 300}}], "run_id": "r"}
    dispatcher = MagicMock()
    dispatcher.dispatch_executor.return_value = SimpleNamespace(report=report)
    monkeypatch.setattr("src.cli.WorkflowRunDispatcher", lambda: dispatcher)
    monkeypatch.setattr("src.cli._load_workflow", lambda *args: executor)
    output = tmp_path / "report.json"
    result = invoke("run", "demo.json", "--node", "a", "--json", "--output", output)
    assert json.loads(result.output)["nodes"] == report["nodes"]
    assert json.loads(output.read_text(encoding="utf-8")) == report
    assert dispatcher.dispatch_executor.call_args.kwargs["target_node_id"] == "a"
    report.update(success=False, stopped=True)
    result = CliRunner().invoke(app, ["run", "demo.json", "--json"])
    assert result.exit_code == 130
    assert json.loads(result.output)["stopped"] is True


@pytest.fixture
def qapp(monkeypatch):
    monkeypatch.setenv("QT_QPA_PLATFORM", "offscreen")
    pytest.importorskip("PySide6")
    from PySide6.QtWidgets import QApplication
    application = QApplication.instance() or QApplication([])
    yield application


@pytest.mark.qt
def test_qt_node_config_and_cli_have_identical_types(qapp):
    from PySide6.QtWidgets import QCheckBox, QSpinBox, QTextEdit
    from src.views.node_properties import NodePropertiesWidget
    from src.cli import _parse_kv_pairs
    checkbox, number, json_editor = QCheckBox(), QSpinBox(), QTextEdit()
    number.setValue(30)
    json_editor.setPlainText('{"x":true}')
    owner = SimpleNamespace(current_config={}, config_widgets={
        "enabled": checkbox, "count": number, "options": json_editor},
        _get_field_type_for_widget=lambda key: "json")
    assert NodePropertiesWidget._collect_current_config(owner) == _parse_kv_pairs([
        "enabled=false", "count=30", 'options={"x":true}'])


@pytest.mark.qt
def test_qt_connection_replacement_updates_saved_model(qapp):
    from src.views.workflow_tab_widget import WorkflowTabWidget, ConnectionInfo
    owner = SimpleNamespace(connections=[ConnectionInfo("a", "output", "c", "input")],
                            _set_modified=MagicMock())
    WorkflowTabWidget._on_connection_created(owner, "b", "output", "c", "input")
    assert [(c.from_node_id, c.to_node_id) for c in owner.connections] == [("b", "c")]


@pytest.mark.qt
def test_qt_history_view_reads_same_record_as_cli(qapp, isolated, tmp_path):
    from PySide6.QtWidgets import QTableWidget
    from src.views.overview_widget import OverviewWidget
    manager = isolated[0]
    manager.config["execution_history"] = [{"id": "startup", "workflow_name": "demo", "status": "failed"}]
    table = QTableWidget(0, 5)
    opened = []
    owner = SimpleNamespace(history_table=table, config_manager=manager,
                            _show_history_report=opened.append)
    OverviewWidget._load_execution_history(owner)
    assert table.rowCount() == 1
    table.cellWidget(0, 4).click()
    assert opened == json.loads(invoke("workflow", "history", "list").output)


@pytest.mark.parametrize("payload,success", [({"model": "demo"}, True), ([], False)])
def test_ai_probe_validates_response(monkeypatch, payload, success):
    from src.core.ai_connection import check_ai_connection
    response = MagicMock(status_code=200, content=b"response")
    response.json.return_value = payload
    post = MagicMock(return_value=response)
    monkeypatch.setattr("src.core.ai_connection._requests.post", post)
    assert check_ai_connection("https://example.test/v1", "fake", "demo")[0] is success
    assert post.call_args.args[0] == "https://example.test/v1/chat/completions"


def test_stop_during_last_node_is_persisted_as_stopped(isolated, tmp_path, monkeypatch):
    path, _ = write_workflow(tmp_path, nodes=[{"node_id": "last", "node_type": "demo", "config": {}}])
    executor = WorkflowExecutor.load_workflow(str(path))
    monkeypatch.setattr(executor, "generate_scripts", lambda *args: [])
    monkeypatch.setattr(executor, "_check_safety_warning", lambda *args: "")
    def complete_and_stop(*args, **kwargs):
        executor.request_stop()
        raise RuntimeError("worker stopped")
    monkeypatch.setattr(executor, "_execute_node_with_details", complete_and_stop)
    report = executor.execute(return_report=True)
    assert report["stopped"] is True
    assert executor.build_execution_record(report)["status"] == "stopped"
    persisted = json.loads((Path(report["artifact_dir"]) / "run.json").read_text(encoding="utf-8"))
    assert persisted["stopped"] is True
