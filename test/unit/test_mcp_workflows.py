import copy
import json
import sys
from unittest.mock import patch

import pytest

from src.core.mcp_workflows import WorkflowService


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "workflows"
    file_path = root / "demo" / "workflow.json"
    file_path.parent.mkdir(parents=True)
    file_path.write_text(json.dumps({
        "version": 2, "workflow_name": "demo",
        "nodes": [{"node_id": "a", "node_type": "test_node", "config": {}}],
        "edges": [],
    }), encoding="utf-8")
    return root, WorkflowService(root)


def test_list_and_read_workflows(workspace):
    root, service = workspace
    listing = service.list_workflows()
    assert listing["workspace"] == str(root)
    assert listing["workflows"][0]["path"] == "demo/workflow.json"
    assert service.get_workflow("demo/workflow.json")["workflow"]["workflow_name"] == "demo"


def test_missing_workspace_lists_empty_without_creating_it(tmp_path):
    root = tmp_path / "missing"
    assert WorkflowService(root).list_workflows()["workflows"] == []
    assert not root.exists()


@pytest.mark.parametrize("path", ["../outside.json", "/outside.json", "missing.json", "demo"])
def test_rejects_invalid_paths(workspace, path):
    _, service = workspace
    with pytest.raises(ValueError):
        service.get_workflow(path)


def test_rejects_symlinks_outside_workspace(workspace, tmp_path):
    root, service = workspace
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "workflow.json").write_text('{"workflow_name":"secret"}')
    (root / "external").symlink_to(outside, target_is_directory=True)
    assert len(service.list_workflows()["workflows"]) == 1
    with pytest.raises(ValueError):
        service.get_workflow("external/workflow.json")


def test_validation_supports_legacy_and_port_edges(workspace):
    root, service = workspace
    file_path = root / "demo/workflow.json"
    data = service.get_workflow(str(file_path))["workflow"]
    data["nodes"].append({"node_id": "b", "node_type": "test_node"})
    for version, edge in [(1, ["a", "b"]), (2, {
        "from_node": "a", "from_port": "result", "to_node": "b", "to_port": "value",
    })]:
        data.update(version=version, edges=[edge])
        file_path.write_text(json.dumps(data))
        result = service.validate_workflow(str(file_path))
        assert result["valid"]
        assert result["execution_order"] == ["a", "b"]
    assert not (root / "demo/runs").exists()


@pytest.mark.parametrize("change", [
    {"workflow_name": "../escape"}, {"workflow_name": "C:\\escape"},
    {"workflow_name": ""}, {"nodes": {}}, {"edges": None}, {"version": "2"},
    {"version": 3}, {"nodes": [{"node_id": "../a", "node_type": "test"}]},
    {"nodes": [{"node_id": "a", "node_type": ""}]},
    {"nodes": [{"node_id": "a", "node_type": "test", "config": []}]},
    {"nodes": [{"node_id": "a", "node_type": "test", "inputs": "bad"}]},
    {"nodes": [{"node_id": "a", "node_type": "test"}] * 2},
    {"edges": [["a", "missing"]]},
    {"edges": [{"from_node": "a", "to_node": "a"}]},
    {"edges": [["a", "a"]]},
])
def test_invalid_workflows_are_reported_and_cannot_run(workspace, change):
    root, service = workspace
    path = root / "demo/workflow.json"
    data = copy.deepcopy(service.get_workflow(str(path))["workflow"])
    data.update(change)
    path.write_text(json.dumps(data))
    result = service.validate_workflow(str(path))
    assert not result["valid"] and result["errors"]
    with patch("src.core.workflow_executor.WorkflowExecutor.load_workflow") as load:
        with pytest.raises(ValueError):
            service.run_workflow(str(path))
        load.assert_not_called()


def test_corrupt_files_do_not_hide_valid_workflows(workspace):
    root, service = workspace
    bad = root / "broken/workflow.json"
    bad.parent.mkdir()
    bad.write_text("{invalid")
    assert not service.validate_workflow(str(bad))["valid"]
    assert len(service.list_workflows()["workflows"]) == 1


def test_run_uses_headless_engine_and_selected_workspace(workspace):
    root, service = workspace
    with patch("src.core.workflow_executor.WorkflowExecutor.load_workflow") as load:
        executor = load.return_value
        executor.prepare_environment.return_value = True
        executor.execute.return_value = {"success": True, "run_id": "run-1"}
        assert service.run_workflow("demo/workflow.json", {"x": 42})["run_id"] == "run-1"
        assert load.call_args.kwargs["uv_manager"].workspace_root == root
        executor.execute.assert_called_once_with(
            initial_data={"x": 42}, return_report=True, trigger_type="mcp"
        )
        executor.prepare_environment.return_value = False
        with pytest.raises(RuntimeError, match="环境准备失败"):
            service.run_workflow("demo/workflow.json")


def test_persisted_runs_and_paged_logs(workspace):
    root, service = workspace
    for run_id in ("20261030-001", "20261030-002"):
        run_dir = root / "demo/runs" / run_id
        run_dir.mkdir(parents=True)
        (run_dir / "run.json").write_text(json.dumps({"run_id": run_id, "success": True}))
        (run_dir / "stdout.log").write_text("第一行\nsecond\nthird\n", encoding="utf-8")
        (run_dir / "stderr.log").write_text("error\n")
    run_id = service.list_runs("demo/workflow.json", limit=1)["runs"][0]["run_id"]
    assert run_id == "20261030-002"
    assert service.get_run("demo/workflow.json", run_id)["success"]
    page = service.get_run_logs("demo/workflow.json", run_id, limit=2)
    assert page["lines"] == ["第一行", "second"] and page["has_more"]
    page = service.get_run_logs("demo/workflow.json", run_id, offset=page["next_offset"])
    assert page["lines"] == ["third"] and not page["has_more"]
    assert service.get_run_logs("demo/workflow.json", run_id, stream="stderr")["lines"] == ["error"]
    with pytest.raises(ValueError):
        service.get_run("demo/workflow.json", "../../escape")
    with pytest.raises(ValueError):
        service.get_run_logs("demo/workflow.json", run_id, stream="run.json")
    with pytest.raises(ValueError):
        service.list_runs("demo/workflow.json", limit=101)


def test_mcp_cli_reports_missing_dependency(monkeypatch, cli_runner):
    from src.cli import app

    monkeypatch.setitem(sys.modules, "mcp.server.stdio", None)
    result = cli_runner.invoke(app, ["mcp"])
    assert result.exit_code == 1
    assert "mozikit[mcp]" in result.output


def test_main_detects_mcp_without_starting_gui(monkeypatch):
    import sys
    from main import _is_cli_mode

    monkeypatch.setattr(sys, "argv", ["main.py", "mcp"])
    assert _is_cli_mode()
