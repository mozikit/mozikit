"""WorkflowRunDispatcher lifecycle tests."""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from src.core.workflow_run_dispatcher import (
    ENVIRONMENT_ERROR,
    WorkflowRunCallbacks,
    WorkflowRunDispatcher,
)


class TestWorkflowRunDispatcher(unittest.TestCase):
    def setUp(self):
        self.config_manager = MagicMock()
        self.runtime_client = MagicMock()
        self.dispatcher = WorkflowRunDispatcher(
            config_manager=self.config_manager,
            runtime_client=self.runtime_client,
        )

    def test_dispatch_executor_runs_full_lifecycle_and_persists_record(self):
        executor = MagicMock()
        executor.workflow_name = "demo"
        executor.prepare_environment.return_value = True
        executor.execute.return_value = {"success": True, "run_id": "run-1"}
        executor.build_execution_record.return_value = {
            "id": "run-1",
            "status": "success",
        }
        events = []
        callbacks = WorkflowRunCallbacks(
            on_environment_preparing=lambda: events.append("preparing"),
            on_environment_ready=lambda success, error: events.append(
                ("ready", success, error)
            ),
        )

        result = self.dispatcher.dispatch_executor(
            executor,
            workflow_path="workflows/demo/workflow.json",
            trigger_type="cli",
            initial_data={"value": 1},
            callbacks=callbacks,
        )

        self.assertEqual(events, ["preparing", ("ready", True, "")])
        self.runtime_client.ensure_running.assert_called_once_with()
        executor.execute.assert_called_once_with(
            initial_data={"value": 1},
            return_report=True,
            trigger_type="cli",
            on_node_start=None,
            on_node_complete=None,
            on_node_progress=None,
            on_node_log=None,
            skip_successful_nodes=False,
        )
        self.config_manager.add_execution_record.assert_called_once_with(result.record)
        self.assertIs(result.report, executor.execute.return_value)

    def test_environment_failure_is_reported_and_persisted(self):
        executor = MagicMock()
        executor.workflow_name = "demo"
        executor.prepare_environment.return_value = False
        ready = MagicMock()

        with self.assertRaisesRegex(RuntimeError, ENVIRONMENT_ERROR):
            self.dispatcher.dispatch_executor(
                executor,
                workflow_path="workflows/demo/workflow.json",
                trigger_type="manual",
                callbacks=WorkflowRunCallbacks(on_environment_ready=ready),
            )

        ready.assert_called_once_with(False, ENVIRONMENT_ERROR)
        executor.execute.assert_not_called()
        record = self.config_manager.add_execution_record.call_args.args[0]
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["trigger_type"], "manual")
        self.assertEqual(record["error"], ENVIRONMENT_ERROR)

    def test_run_loads_workflow_and_returns_report(self):
        executor = MagicMock()
        executor.workflow_name = "demo"
        executor.prepare_environment.return_value = True
        executor.execute.return_value = {"success": True}
        executor.build_execution_record.return_value = {"status": "success"}

        with tempfile.TemporaryDirectory() as directory:
            workflow_path = Path(directory) / "workflow.json"
            workflow_path.touch()
            with patch.object(
                self.dispatcher, "load_workflow", return_value=executor
            ) as load_workflow:
                report = self.dispatcher.run(
                    str(workflow_path),
                    trigger_type="scheduled",
                    initial_data={"event": "tick"},
                )

        load_workflow.assert_called_once_with(str(workflow_path), None)
        self.assertEqual(report, {"success": True})
        self.assertEqual(
            executor.execute.call_args.kwargs["initial_data"], {"event": "tick"}
        )

    def test_missing_workflow_creates_failed_record(self):
        missing = "does-not-exist/workflow.json"

        with self.assertRaises(Exception):
            self.dispatcher.dispatch(
                missing,
                trigger_type="trigger",
                workflow_name="missing-demo",
            )

        record = self.config_manager.add_execution_record.call_args.args[0]
        self.assertEqual(record["status"], "failed")
        self.assertEqual(record["workflow_path"], missing)
        self.assertEqual(record["workflow_name"], "missing-demo")
        self.assertEqual(record["trigger_type"], "trigger")


if __name__ == "__main__":
    unittest.main()
