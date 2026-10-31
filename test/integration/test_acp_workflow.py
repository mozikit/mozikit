"""Workflow engine and CLI integration with an independent ACP agent process."""

import json
import os
import signal
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.core.config_manager import ConfigManager
from src.core.node_base import CustomNode
from src.core.uv_manager import UVManager
from src.core.workflow_executor import WorkflowExecutor


ROOT = Path(__file__).resolve().parents[2]
AGENT = ROOT / "test" / "fixtures" / "fake_acp_agent.py"


def build_executor(tmp_path, mode="normal", **config):
    uv = UVManager(str(tmp_path / "workflows"))
    uv.create_workflow_env = Mock(
        side_effect=AssertionError("Native-only workflow needs no venv")
    )
    uv.start_worker = Mock(
        side_effect=AssertionError("Native-only workflow needs no Python worker")
    )
    manager = ConfigManager(tmp_path / "config.json")
    executor = WorkflowExecutor("acp-demo", uv, manager)
    executor.add_node(
        CustomNode(
            "agent",
            "acp_agent",
            {
                "agent": sys.executable,
                "args": [str(AGENT), mode, str(tmp_path / "wire.jsonl")],
                "prompt": "Summarize {% topic %}",
                **config,
            },
        )
    )
    executor.add_node(CustomNode("result", "debug", {"show_timestamp": False}))
    executor.add_edge("agent", "text", "result", "input")
    return executor


def read_wire(tmp_path):
    return [
        json.loads(line) for line in (tmp_path / "wire.jsonl").read_text().splitlines()
    ]


def wait_for_prompt(path, process=None, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.exists() and '"method": "session/prompt"' in path.read_text():
            return
        if process is not None:
            assert process.poll() is None
        time.sleep(0.02)
    pytest.fail("Agent did not receive the prompt")


def test_acp_node_streams_into_report_and_routes_reply_to_downstream(tmp_path):
    executor = build_executor(tmp_path)
    logs, progress = [], []
    assert executor.prepare_environment()
    report = executor.execute(
        initial_data={"topic": "workflow"},
        return_report=True,
        on_node_log=lambda node, line: logs.append((node, line)),
        on_node_progress=lambda *args: progress.append(args),
    )
    assert report["success"], report["error"]
    assert report["final_context"]["value"] == "你好，ACP"
    assert report["nodes"][0]["script_path"] == ""
    assert "[ACP tool] Inspect: in_progress" in report["nodes"][0]["stdout"]
    assert any("你好，" in line for node, line in logs if node == "agent")
    assert progress[-1] == ("agent", 100, "Agent 已完成")
    output = report["nodes"][0]["output"]
    assert output["session_id"] == "test-session"
    assert output["stop_reason"] == "end_turn"
    assert len(output["updates"]) == 5
    saved = json.loads((Path(report["artifact_dir"]) / "run.json").read_text())
    assert saved["nodes"] == report["nodes"]
    prompt = next(r for r in read_wire(tmp_path) if r.get("method") == "session/prompt")
    assert prompt["params"]["prompt"] == [
        {"type": "text", "text": "Summarize workflow"}
    ]
    initialize = next(
        r for r in read_wire(tmp_path) if r.get("method") == "session/new"
    )
    assert (
        Path(initialize["params"]["cwd"])
        == (tmp_path / "workflows" / "acp-demo").resolve()
    )


def test_upstream_prompt_port_overrides_empty_config_and_resolves_relative_directory(
    tmp_path,
):
    executor = build_executor(tmp_path, prompt="", cwd="artifacts")
    executor.add_node(CustomNode("input", "debug", {}))
    executor.add_edge("input", "value", "agent", "prompt")
    report = executor.execute(
        initial_data={"input": "Use this upstream prompt"}, return_report=True
    )
    assert report["success"], report["error"]
    prompt = next(r for r in read_wire(tmp_path) if r.get("method") == "session/prompt")
    assert prompt["params"]["prompt"][0]["text"] == "Use this upstream prompt"
    session = next(r for r in read_wire(tmp_path) if r.get("method") == "session/new")
    assert (
        Path(session["params"]["cwd"])
        == (tmp_path / "workflows" / "acp-demo" / "artifacts").resolve()
    )


@pytest.mark.parametrize(
    "mode,code",
    [
        ("refusal", "ACP_TURN_INCOMPLETE"),
        ("max_tokens", "ACP_TURN_INCOMPLETE"),
        ("cancelled", "ACP_CANCELLED"),
        ("exit-prompt", "ACP_PROCESS_EXITED"),
    ],
)
def test_incomplete_turn_stops_downstream_and_preserves_error_code(
    tmp_path, mode, code
):
    executor = build_executor(tmp_path, mode)
    report = executor.execute(initial_data={"topic": "x"}, return_report=True)
    assert not report["success"]
    assert report["failed_node_id"] == "agent"
    assert code in report["nodes"][0]["error"]
    assert [node["node_id"] for node in report["nodes"]] == ["agent"]


def test_host_node_timeout_cannot_be_extended_by_node_config(tmp_path):
    executor = build_executor(tmp_path, "wait", timeout=60)
    executor.config_manager.get_node_timeout_seconds = lambda: 0.2
    report = executor.execute(return_report=True)
    assert not report["success"]
    assert "ACP_TIMEOUT" in report["nodes"][0]["error"]
    assert any(r.get("method") == "session/cancel" for r in read_wire(tmp_path))


def test_gui_style_stop_request_cancels_agent_and_marks_workflow_stopped(tmp_path):
    executor = build_executor(tmp_path, "wait")
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(executor.execute, return_report=True)
        try:
            wait_for_prompt(tmp_path / "wire.jsonl")
        finally:
            executor.request_stop()
        report = future.result(timeout=10)
    assert report["stopped"]
    assert not report["success"]
    assert [node["node_id"] for node in report["nodes"]] == ["agent"]
    assert "ACP_CANCELLED" in report["nodes"][0]["error"]
    assert any(r.get("method") == "session/cancel" for r in read_wire(tmp_path))


def cli_environment(tmp_path, mode="normal"):
    workspace = tmp_path / "workflows"
    workflow = workspace / "acp-demo" / "workflow.json"
    workflow.parent.mkdir(parents=True)
    workflow.write_text(
        json.dumps(
            {
                "version": 2,
                "workflow_name": "acp-demo",
                "active": False,
                "nodes": [
                    {
                        "node_id": "agent",
                        "node_type": "acp_agent",
                        "config": {
                            "agent": sys.executable,
                            "args": [str(AGENT), mode, str(tmp_path / "wire.jsonl")],
                            "prompt": "Summarize {% topic %}",
                        },
                    },
                    {"node_id": "result", "node_type": "debug", "config": {}},
                ],
                "edges": [
                    {
                        "from_node": "agent",
                        "from_port": "text",
                        "to_node": "result",
                        "to_port": "input",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    app_data = tmp_path / "app-data"
    env = dict(
        os.environ,
        MOZIKIT_WORKSPACE=str(workspace),
        MOZIKIT_APP_DATA_DIR=str(app_data),
        MOZIKIT_CONFIG_PATH=str(app_data / "config.json"),
        PYTHONPATH=str(ROOT),
        PYTHONIOENCODING="utf-8",
    )
    return workflow, env


def test_cli_workflow_and_history_roundtrip_with_acp_node(tmp_path):
    workflow, env = cli_environment(tmp_path)

    def cli(*args):
        result = subprocess.run(
            [sys.executable, str(ROOT / "main.py"), *map(str, args)],
            cwd=tmp_path,
            env=env,
            capture_output=True,
            text=True,
            timeout=15,
        )
        assert result.returncode == 0, result.stdout + result.stderr
        return json.loads(result.stdout)

    report = cli("run", workflow, "--input", '{"topic":"ACP"}', "--json")
    assert report["success"]
    assert report["final_context"]["value"] == "你好，ACP"
    assert "[ACP tool]" in report["nodes"][0]["stdout"]
    history = cli("workflow", "history", "list", "--workflow", "acp-demo")
    assert len(history) == 1
    stored = cli("workflow", "history", "show", report["run_id"])
    assert stored["nodes"] == report["nodes"]


@pytest.mark.skipif(os.name == "nt", reason="POSIX SIGINT integration")
def test_cli_workflow_sigint_produces_stopped_report(tmp_path):
    workflow, env = cli_environment(tmp_path, "wait")
    process = subprocess.Popen(
        [sys.executable, str(ROOT / "main.py"), "run", str(workflow), "--json"],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        wait_for_prompt(tmp_path / "wire.jsonl", process)
        process.send_signal(signal.SIGINT)
        stdout, stderr = process.communicate(timeout=10)
        assert process.returncode == 130, stderr
        report = json.loads(stdout)
        assert report["stopped"]
        assert any(r.get("method") == "session/cancel" for r in read_wire(tmp_path))
    finally:
        if process.poll() is None:
            process.kill()
            process.communicate(timeout=10)
