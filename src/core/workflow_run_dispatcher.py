"""Shared lifecycle for one workflow run.

The dispatcher owns the process-independent execution steps used by CLI,
schedulers, GUI adapters, and future persistent triggers.  Presentation,
threading, cancellation controls, and scheduling policy stay with callers.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Optional
import uuid

from .config_manager import ConfigManager
from .exceptions import ErrorCode, LocalFlowError
from .runtime_client import RuntimeClient
from .workflow_executor import WorkflowExecutor


ENVIRONMENT_ERROR = "环境准备失败，请检查 UV 安装和依赖配置"


@dataclass(frozen=True)
class WorkflowRunCallbacks:
    on_environment_preparing: Optional[Callable[[], None]] = None
    on_environment_ready: Optional[Callable[[bool, str], None]] = None
    on_node_start: Optional[Callable[[str], None]] = None
    on_node_complete: Optional[Callable[[dict], None]] = None
    on_node_progress: Optional[Callable[[str, int, str], None]] = None
    on_node_log: Optional[Callable[[str, str], None]] = None


@dataclass(frozen=True)
class WorkflowDispatchResult:
    report: dict
    record: dict


class WorkflowRunDispatcher:
    """Turn one run request into an execution report and history record."""

    def __init__(
        self,
        config_manager: Optional[ConfigManager] = None,
        runtime_client: Optional[RuntimeClient] = None,
    ) -> None:
        self.config_manager = config_manager or ConfigManager()
        self.runtime_client = runtime_client or RuntimeClient()

    def load_workflow(self, workflow_path: str, uv_manager=None) -> WorkflowExecutor:
        path = Path(workflow_path)
        if not path.exists():
            raise LocalFlowError(
                ErrorCode.FILE_NOT_FOUND, f"工作流文件不存在: {workflow_path}"
            )
        if not path.is_file():
            raise LocalFlowError(
                ErrorCode.FILE_NOT_FOUND, f"工作流路径不是文件: {workflow_path}"
            )
        return WorkflowExecutor.load_workflow(str(path), uv_manager)

    def run(
        self,
        workflow_path: str,
        *,
        trigger_type: str,
        initial_data: Optional[dict[str, Any]] = None,
        callbacks: Optional[WorkflowRunCallbacks] = None,
        prepare_environment: bool = True,
        skip_successful_nodes: bool = False,
        uv_manager=None,
        workflow_name: Optional[str] = None,
    ) -> dict:
        """Load and synchronously execute one workflow, returning its report."""
        return self.dispatch(
            workflow_path,
            trigger_type=trigger_type,
            initial_data=initial_data,
            callbacks=callbacks,
            prepare_environment=prepare_environment,
            skip_successful_nodes=skip_successful_nodes,
            uv_manager=uv_manager,
            workflow_name=workflow_name,
        ).report

    def dispatch(
        self,
        workflow_path: str,
        *,
        trigger_type: str,
        initial_data: Optional[dict[str, Any]] = None,
        callbacks: Optional[WorkflowRunCallbacks] = None,
        prepare_environment: bool = True,
        skip_successful_nodes: bool = False,
        uv_manager=None,
        workflow_name: Optional[str] = None,
    ) -> WorkflowDispatchResult:
        try:
            executor = self.load_workflow(workflow_path, uv_manager)
        except Exception as exc:
            self._persist_startup_failure(
                workflow_path,
                trigger_type,
                exc,
                workflow_name=workflow_name,
            )
            raise
        return self.dispatch_executor(
            executor,
            workflow_path=workflow_path,
            trigger_type=trigger_type,
            initial_data=initial_data,
            callbacks=callbacks,
            prepare_environment=prepare_environment,
            skip_successful_nodes=skip_successful_nodes,
        )

    def dispatch_executor(
        self,
        executor: WorkflowExecutor,
        *,
        workflow_path: str,
        trigger_type: str,
        initial_data: Optional[dict[str, Any]] = None,
        callbacks: Optional[WorkflowRunCallbacks] = None,
        prepare_environment: bool = True,
        skip_successful_nodes: bool = False,
    ) -> WorkflowDispatchResult:
        callbacks = callbacks or WorkflowRunCallbacks()
        try:
            if prepare_environment:
                self._notify(callbacks.on_environment_preparing)
                if not executor.prepare_environment():
                    self._notify(
                        callbacks.on_environment_ready, False, ENVIRONMENT_ERROR
                    )
                    raise RuntimeError(ENVIRONMENT_ERROR)
                self._notify(callbacks.on_environment_ready, True, "")

            self.runtime_client.ensure_running()
            report = executor.execute(
                initial_data=initial_data,
                return_report=True,
                trigger_type=trigger_type,
                on_node_start=callbacks.on_node_start,
                on_node_complete=callbacks.on_node_complete,
                on_node_progress=callbacks.on_node_progress,
                on_node_log=callbacks.on_node_log,
                skip_successful_nodes=skip_successful_nodes,
            )
        except Exception as exc:
            self._persist_startup_failure(
                workflow_path,
                trigger_type,
                exc,
                workflow_name=executor.workflow_name,
            )
            raise

        record = executor.build_execution_record(
            report,
            workflow_path=workflow_path,
            trigger_type=trigger_type,
        )
        self.config_manager.add_execution_record(record)
        return WorkflowDispatchResult(report=report, record=record)

    def _persist_startup_failure(
        self,
        workflow_path: str,
        trigger_type: str,
        exc: Exception,
        *,
        workflow_name: Optional[str] = None,
    ) -> dict:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        record = {
            "id": str(uuid.uuid4())[:8],
            "workflow_name": workflow_name or Path(workflow_path).parent.name,
            "workflow_path": workflow_path,
            "status": "failed",
            "started_at": now,
            "finished_at": now,
            "duration_ms": 0,
            "output": None,
            "error": str(exc),
            "trigger_type": trigger_type,
            "artifact_dir": "",
        }
        self.config_manager.add_execution_record(record)
        return record

    @staticmethod
    def _notify(callback: Optional[Callable], *args) -> None:
        if callback is not None:
            callback(*args)
