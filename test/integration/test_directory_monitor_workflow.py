"""End-to-end directory monitor graph tests."""

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

from src.core.config_manager import ConfigManager
from src.core.trigger_manager import TriggerManager
from src.core.trigger_registry import TriggerRegistry
from src.core.folder_watch_trigger import FolderWatchTrigger
from src.core.uv_manager import UVManager
from src.core.workflow_run_dispatcher import WorkflowRunDispatcher


class CapturingDispatcher(WorkflowRunDispatcher):
    def __init__(self, uv_manager, config_manager):
        super().__init__(config_manager=config_manager, runtime_client=MagicMock())
        self.uv_manager = uv_manager
        self.create_workflow_env = MagicMock(return_value=False)
        self.uv_manager.create_workflow_env = self.create_workflow_env
        self.reports = []
        self._lock = threading.Lock()

    def run(self, workflow_path, **kwargs):
        kwargs["uv_manager"] = self.uv_manager
        report = super().run(workflow_path, **kwargs)
        with self._lock:
            self.reports.append(report)
        return report


def _write_workflow(path: Path, first_root: Path, second_root: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "workflow_id": "directory-workflow",
                "workflow_name": "Directory workflow",
                "active": True,
                "triggers": [],
                "nodes": [
                    {
                        "node_id": "watch-one",
                        "node_type": "folder_watch",
                        "config": {
                            "path": str(first_root),
                            "events": ["created"],
                            "include": ["*.txt"],
                            "settle_ms": 0,
                            "debounce_ms": 0,
                        },
                    },
                    {
                        "node_id": "debug-one",
                        "node_type": "debug",
                        "config": {"show_timestamp": False},
                    },
                    {
                        "node_id": "watch-two",
                        "node_type": "folder_watch",
                        "config": {
                            "path": str(second_root),
                            "events": ["created"],
                            "include": ["*.txt"],
                            "settle_ms": 0,
                            "debounce_ms": 0,
                        },
                    },
                    {
                        "node_id": "debug-two",
                        "node_type": "debug",
                        "config": {"show_timestamp": False},
                    },
                ],
                "edges": [
                    {
                        "from_node": "watch-one",
                        "from_port": "event",
                        "to_node": "debug-one",
                        "to_port": "input",
                    },
                    {
                        "from_node": "watch-two",
                        "from_port": "event",
                        "to_node": "debug-two",
                        "to_port": "input",
                    },
                ],
            }
        ),
        encoding="utf-8",
    )


def _wait_for_reports(dispatcher, count, timeout=5):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        with dispatcher._lock:
            if len(dispatcher.reports) >= count:
                return list(dispatcher.reports)
        time.sleep(0.05)
    with dispatcher._lock:
        return list(dispatcher.reports)


def test_directory_event_reaches_only_its_downstream_debug_node(tmp_path):
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    first_root.mkdir()
    second_root.mkdir()
    workflow_path = tmp_path / "workflows" / "directory" / "workflow.json"
    _write_workflow(workflow_path, first_root, second_root)

    config_manager = ConfigManager(tmp_path / "config.json")
    uv_manager = UVManager(str(tmp_path / "execution"))
    dispatcher = CapturingDispatcher(uv_manager, config_manager)
    registry = TriggerRegistry()
    registry.register("folder_watch", FolderWatchTrigger)
    manager = TriggerManager(
        tmp_path / "workflows",
        registry=registry,
        dispatcher=dispatcher,
        state_path=tmp_path / "trigger-state.json",
        reconcile_interval=0.05,
    )

    try:
        status = manager.reconcile()
        assert status["desired"] == [
            "directory-workflow/watch-one",
            "directory-workflow/watch-two",
        ]

        (first_root / "first.txt").write_text("one", encoding="utf-8")
        reports = _wait_for_reports(dispatcher, 1)
        assert len(reports) == 1
        dispatcher.create_workflow_env.assert_not_called()
        assert [item["node_id"] for item in reports[0]["nodes"]] == [
            "watch-one",
            "debug-one",
        ]
        assert reports[0]["nodes"][-1]["output"]["value"]["event_type"] == "created"
        assert reports[0]["nodes"][-1]["output"]["value"]["path"].endswith("first.txt")

        (second_root / "second.txt").write_text("two", encoding="utf-8")
        reports = _wait_for_reports(dispatcher, 2)
        assert len(reports) == 2
        assert [item["node_id"] for item in reports[1]["nodes"]] == [
            "watch-two",
            "debug-two",
        ]
        assert reports[1]["nodes"][-1]["output"]["value"]["path"].endswith(
            "second.txt"
        )

        manager.deactivate_workflow("directory-workflow")
        stopped_count = len(dispatcher.reports)
        (first_root / "after-stop.txt").write_text("ignored", encoding="utf-8")
        time.sleep(0.3)
        assert len(dispatcher.reports) == stopped_count
        assert manager.status()["actual"] == {}
    finally:
        manager.stop()
