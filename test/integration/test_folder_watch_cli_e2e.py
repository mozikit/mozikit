"""Real CLI/Runtime Daemon/FolderWatchTrigger acceptance coverage."""

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest


def wait_for(predicate, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        value = predicate()
        if value:
            return value
        time.sleep(0.05)
    return predicate()


def wait_until_stable(reader, samples=5, interval=0.1, timeout=5):
    deadline = time.monotonic() + timeout
    previous = object()
    stable = 0
    while time.monotonic() < deadline:
        current = reader()
        if current == previous:
            stable += 1
            if stable >= samples:
                return current
        else:
            previous, stable = current, 0
        time.sleep(interval)
    return reader()


def cli(env, *arguments):
    command = [sys.executable, "-c", "from src.cli import run_cli; run_cli()", *arguments]
    return subprocess.run(command, cwd=Path(__file__).parents[2], env=env, text=True, capture_output=True, timeout=20)


@pytest.mark.slow
def test_real_cli_daemon_folder_watch_lifecycle(tmp_path):
    workspace = tmp_path / "workspace"
    watch_path = workspace / "demo" / "watch"
    app_data = tmp_path / "app-data"
    watch_path.mkdir(parents=True)
    workflow_path = workspace / "demo" / "workflow.json"
    workflow_path.write_text(json.dumps({
        "workflow_id": "e2e-workflow",
        "workflow_name": "Folder Watch E2E",
        "active": False,
        "triggers": [],
        "nodes": [],
        "edges": [],
    }), encoding="utf-8")

    env = os.environ.copy()
    env.update({
        "MOZIKIT_WORKSPACE": str(workspace),
        "MOZIKIT_APP_DATA_DIR": str(app_data),
        "PYTHONPATH": str(Path(__file__).parents[2]) + os.pathsep + env.get("PYTHONPATH", ""),
    })
    daemon = subprocess.Popen(
        [sys.executable, "-m", "src.core.runtime_daemon"],
        cwd=Path(__file__).parents[2], env=env,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        connection = app_data / "runtime" / "connection.json"
        assert wait_for(connection.is_file), "Runtime Daemon did not start"

        added = cli(env, "workflow", "trigger", "add", "demo", "folder_watch",
                    "--id", "save-watch", "--path", str(watch_path),
                    "--event", "created", "--event", "modified",
                    "--include", "*.sav", "--settle", "0", "--debounce", "200")
        assert added.returncode == 0, added.stdout + added.stderr

        activated = cli(env, "workflow", "activate", "demo")
        assert activated.returncode == 0, activated.stdout + activated.stderr

        def running_status():
            result = cli(env, "workflow", "status", "demo", "--json")
            if result.returncode != 0:
                return None
            document = json.loads(result.stdout)
            return document if document["triggers"] and document["triggers"][0]["status"] == "running" else None

        assert wait_for(running_status), "FolderWatchTrigger did not become running"

        target = watch_path / "save01.sav"
        target.write_text("created", encoding="utf-8")
        history_path = app_data / "config.json"

        def execution_history():
            if not history_path.is_file():
                return []
            try:
                return json.loads(history_path.read_text(encoding="utf-8")).get("execution_history", [])
            except (OSError, json.JSONDecodeError):
                return []

        assert wait_for(lambda: len(execution_history()) >= 1), "file event did not create an execution"
        new_watch_path = workspace / "demo" / "new-watch"
        new_watch_path.mkdir()
        changed = cli(env, "workflow", "trigger", "set", "demo", "save-watch",
                      "--path", str(new_watch_path))
        assert changed.returncode == 0, changed.stdout + changed.stderr

        def reconciled():
            result = cli(env, "workflow", "status", "demo", "--json")
            if result.returncode != 0:
                return False
            document = json.loads(result.stdout)
            if not document["triggers"]:
                return False
            runtime_config = document["triggers"][0].get("runtime_config") or {}
            return runtime_config.get("path") == str(new_watch_path)

        assert wait_for(
            reconciled
        ), "active Trigger configuration was not reconciled"
        baseline_before_new_path = len(execution_history())
        (watch_path / "old-path.sav").write_text("old", encoding="utf-8")
        assert not wait_for(lambda: len(execution_history()) > baseline_before_new_path, timeout=1)
        (new_watch_path / "new-path.sav").write_text("new", encoding="utf-8")
        assert wait_for(lambda: len(execution_history()) > baseline_before_new_path)
        deactivated = cli(env, "workflow", "deactivate", "demo")
        assert deactivated.returncode == 0, deactivated.stdout + deactivated.stderr
        assert wait_for(lambda: json.loads(cli(env, "workflow", "status", "demo", "--json").stdout)["triggers"][0]["status"] == "stopped")
        baseline = len(wait_until_stable(execution_history))

        target.write_text("after deactivate", encoding="utf-8")
        assert not wait_for(lambda: len(execution_history()) > baseline, timeout=1)
    finally:
        cli(env, "runtime", "stop")
        try:
            daemon.wait(timeout=5)
        except subprocess.TimeoutExpired:
            daemon.terminate()
            daemon.wait(timeout=5)
