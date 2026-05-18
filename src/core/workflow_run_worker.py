"""
工作流执行 Worker
在后台线程中执行工作流，通过 Signal 实时通知 UI 进度
"""
from PySide6.QtCore import QThread, Signal


class WorkflowRunWorker(QThread):
    """
    在后台线程中执行工作流

    Signals:
        node_started(str): 单个节点开始执行，参数为 node_id
        node_completed(dict): 单个节点完成，参数为 node_report
        node_progress(str, int, str): 节点进度更新，参数为 (node_id, percent, message)
        node_log(str, str): 实时日志行，参数为 (node_id, line)
        finished_with_report(dict): 整个工作流完成，参数为完整 report
        error(str): 执行出错，参数为错误信息
        environment_preparing(): 环境准备开始
        environment_ready(bool, str): 环境准备完成，参数为 (success, error_message)
    """

    node_started = Signal(str)
    node_completed = Signal(dict)
    node_progress = Signal(str, int, str)
    node_log = Signal(str, str)
    finished_with_report = Signal(dict)
    error = Signal(str)
    environment_preparing = Signal()
    environment_ready = Signal(bool, str)

    def __init__(
        self,
        executor,
        trigger_type: str = "manual",
        prepare_env: bool = True,
        skip_successful_nodes: bool = False,
        parent=None,
    ):
        super().__init__(parent)
        self.executor = executor
        self.trigger_type = trigger_type
        self.prepare_env = prepare_env
        self.skip_successful_nodes = skip_successful_nodes

    def request_stop(self):
        self.executor.request_stop()

    def run(self):
        try:
            if self.prepare_env:
                self.environment_preparing.emit()
                env_success = self.executor.prepare_environment()
                if not env_success:
                    error_msg = "环境准备失败，请检查UV安装和依赖配置"
                    self.environment_ready.emit(False, error_msg)
                    self.error.emit(error_msg)
                    return
                self.environment_ready.emit(True, "")

            report = self.executor.execute(
                return_report=True,
                trigger_type=self.trigger_type,
                on_node_start=self._on_node_start,
                on_node_complete=self._on_node_complete,
                on_node_progress=self._on_node_progress,
                on_node_log=self._on_node_log,
                skip_successful_nodes=self.skip_successful_nodes,
            )
            self.finished_with_report.emit(report)
        except Exception as e:
            self.error.emit(str(e))

    def _on_node_start(self, node_id: str):
        self.node_started.emit(node_id)

    def _on_node_complete(self, node_report: dict):
        self.node_completed.emit(node_report)

    def _on_node_progress(self, node_id: str, percent: int, message: str):
        self.node_progress.emit(node_id, percent, message)

    def _on_node_log(self, node_id: str, line: str):
        self.node_log.emit(node_id, line)
