"""Real subprocess commands, isolated runtime, and persisted report roundtrip."""
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def test_cli_target_run_and_history_roundtrip(tmp_path):
    root = Path(__file__).resolve().parents[2]
    workspace = tmp_path / "workflows"
    workflow = workspace / "demo" / "workflow.json"
    workflow.parent.mkdir(parents=True)
    app_data = tmp_path / "app-data"
    env = dict(os.environ, MOZIKIT_WORKSPACE=str(workspace),
               MOZIKIT_APP_DATA_DIR=str(app_data),
               MOZIKIT_CONFIG_PATH=str(app_data / "config.json"),
               PYTHONPATH=str(root), PYTHONIOENCODING="utf-8")
    document = {
        "version": 2, "workflow_id": "parity", "workflow_name": "demo", "active": False,
        "nodes": [{"node_id": name, "node_type": "debug", "config": {}}
                  for name in ("a", "b", "sibling")],
        "edges": [{"from_node": "a", "from_port": "output", "to_node": target, "to_port": "input"}
                  for target in ("b", "sibling")],
        "canvas_state": {"scale_x": 1.5, "offset_y": 55},
    }
    workflow.write_text(json.dumps(document), encoding="utf-8")
    def cli(*args):
        result = subprocess.run([sys.executable, "-c", "from src.cli import run_cli; run_cli()", *map(str, args)],
                                cwd=tmp_path, env=env, capture_output=True, text=True,
                                encoding="utf-8", timeout=25)
        assert result.returncode == 0, result.stdout + result.stderr
        return result.stdout

    # This test owns the process handle and an independent runtime directory.
    daemon = subprocess.Popen([sys.executable, "-m", "src.core.runtime_daemon"], cwd=tmp_path,
                              env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        connection = app_data / "runtime" / "connection.json"
        deadline = time.monotonic() + 10
        while not connection.exists() and daemon.poll() is None and time.monotonic() < deadline:
            time.sleep(0.05)
        assert connection.exists(), "isolated Runtime Daemon failed to start"
        cli("workflow", "update-node", workflow, "b", "show_timestamp=false", "max_length=500")
        updated = json.loads(workflow.read_text(encoding="utf-8"))
        assert updated["canvas_state"] == document["canvas_state"]
        assert updated["nodes"][1]["config"] == {"show_timestamp": False, "max_length": 500}
        output = tmp_path / "report.json"
        report = json.loads(cli("run", workflow, "--node", "b", "--json", "--output", output,
                                "--input", '{"message":"parity"}'))
        assert report["success"]
        assert report["execution_order"] == ["a", "b"]
        assert [node["node_id"] for node in report["nodes"]] == ["a", "b"]
        stored = json.loads(output.read_text(encoding="utf-8"))
        assert stored["nodes"] == report["nodes"]
        history = json.loads(cli("workflow", "history", "list", "--workflow", "demo"))
        assert len(history) == 1
        assert history[0]["id"] == report["run_id"]
        assert json.loads(cli("workflow", "history", "show", report["run_id"])) == stored
    finally:
        if daemon.poll() is None:
            try:
                cli("runtime", "stop")
                daemon.wait(timeout=10)
            except (AssertionError, subprocess.TimeoutExpired):
                daemon.terminate()
                daemon.wait(timeout=5)
