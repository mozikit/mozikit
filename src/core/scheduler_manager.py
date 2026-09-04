"""
定时任务管理器
负责工作流的定时执行调度
"""

import threading
import uuid
from datetime import datetime, timedelta
from typing import Callable, List, Tuple

from PySide6.QtCore import QTimer, Signal, QObject

from .config_manager import ConfigManager
from .uv_manager import UVManager
from .log_manager import get_logger

logger = get_logger("scheduler_manager")
from .workflow_run_dispatcher import WorkflowRunDispatcher


from .cron_utils import CronUtils


class ScheduleEntry(CronUtils):
    """定时任务条目（继承自 CronUtils，保持 API 兼容）"""
    pass


class SchedulerManager(QObject):
    """定时任务管理器"""

    task_started = Signal(dict)  # 任务开始信号
    task_finished = Signal(dict)  # 任务完成信号
    task_failed = Signal(dict, str)  # 任务失败信号

    def __init__(self, config_manager: ConfigManager = None):
        super().__init__()
        self.config_manager = config_manager or ConfigManager()
        self.uv_manager = UVManager()
        self.dispatcher = WorkflowRunDispatcher(config_manager=self.config_manager)

        self._timers = {}  # task_id -> QTimer
        self._running_tasks = {}  # task_id -> bool
        self._callbacks = {}  # task_id -> Callable

        self._start_scheduler()

    def _start_scheduler(self):
        """启动调度器"""
        self._scheduler_timer = QTimer()
        self._scheduler_timer.timeout.connect(self._check_schedules)
        self._scheduler_timer.start(1000)  # 每秒检查一次

    def _check_schedules(self):
        """检查所有定时任务"""
        now = datetime.now()
        current_time = now.strftime("%Y-%m-%d %H:%M:%S")

        for task in self.config_manager.get_scheduled_tasks():
            if not task.get("enabled", True):
                continue

            next_run = task.get("next_run", "")
            workflow_name = task.get("workflow_name", "")

            if next_run and next_run <= current_time:
                self._execute_task(task)

                next_time = ScheduleEntry.format_next_run(
                    task.get("cron_expression", "0 * * * *")
                )
                task["next_run"] = next_time.strftime("%Y-%m-%d %H:%M:%S")
                self.config_manager.update_scheduled_task(
                    task["id"], {"next_run": task["next_run"], "last_run": current_time}
                )

    def _execute_task(self, task: dict):
        """执行定时任务"""
        task_id = task.get("id")
        workflow_path = task.get("workflow_path", "")

        if self._running_tasks.get(task_id, False):
            return

        self._running_tasks[task_id] = True

        self.task_started.emit(task)

        def run_workflow():
            try:
                result = self.dispatcher.dispatch(
                    workflow_path,
                    trigger_type="scheduled",
                    uv_manager=self.uv_manager,
                    workflow_name=task.get("workflow_name"),
                )
                report = result.report
                record = result.record
                if report.get("success"):
                    self.task_finished.emit(record)
                else:
                    self.task_failed.emit(task, report.get("error", "执行失败"))

            except Exception as e:
                import traceback

                traceback.print_exc()

                self.task_failed.emit(task, str(e))

            finally:
                self._running_tasks[task_id] = False

        thread = threading.Thread(target=run_workflow, daemon=True)
        thread.start()

    def add_task(
        self, workflow_name: str, workflow_path: str, cron_expr: str = "0 * * * *"
    ) -> str:
        """添加定时任务

        Args:
            workflow_name: 工作流名称
            workflow_path: 工作流文件路径
            cron_expr: Cron表达式

        Returns:
            任务ID
        """
        cron_expr = self.validate_cron_expression(cron_expr)
        task_id = str(uuid.uuid4())[:8]
        next_run = ScheduleEntry.format_next_run(cron_expr)

        task = {
            "id": task_id,
            "workflow_name": workflow_name,
            "workflow_path": workflow_path,
            "cron_expression": cron_expr,
            "enabled": True,
            "next_run": next_run.strftime("%Y-%m-%d %H:%M:%S"),
            "last_run": None,
            "created_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

        self.config_manager.add_scheduled_task(task)
        return task_id

    def update_task(self, task_id: str, **updates) -> bool:
        """更新任务"""
        if "cron_expression" in updates:
            normalized = self.validate_cron_expression(updates["cron_expression"])
            next_run = ScheduleEntry.format_next_run(normalized)
            updates["cron_expression"] = normalized
            updates["next_run"] = next_run.strftime("%Y-%m-%d %H:%M:%S")
        return self.config_manager.update_scheduled_task(task_id, updates)

    def delete_task(self, task_id: str) -> bool:
        """删除任务"""
        if task_id in self._timers:
            self._timers[task_id].stop()
            del self._timers[task_id]
        return self.config_manager.delete_scheduled_task(task_id)

    def get_tasks(self) -> list:
        """获取所有任务"""
        return self.config_manager.get_scheduled_tasks()

    def get_task(self, task_id: str) -> dict:
        """获取指定任务"""
        return self.config_manager.get_scheduled_task(task_id)

    def set_callback(self, task_id: str, callback: Callable):
        """设置任务回调"""
        self._callbacks[task_id] = callback

    def run_now(self, task_id: str):
        """立即运行任务"""
        task = self.get_task(task_id)
        if task:
            self._execute_task(task)

    def is_task_running(self, task_id: str) -> bool:
        """检查任务是否正在运行"""
        return self._running_tasks.get(task_id, False)

    def get_preset_intervals(self) -> list:
        """获取预设时间间隔"""
        return [
            {"name": "每分钟", "value": "minutely", "cron": "*/1 * * * *"},
            {"name": "每小时", "value": "hourly", "cron": "0 * * * *"},
            {"name": "每天", "value": "daily", "cron": "0 0 * * *"},
            {"name": "每周", "value": "weekly", "cron": "0 0 * * 0"},
            {"name": "每月", "value": "monthly", "cron": "0 0 1 * *"},
        ]

    def validate_cron_expression(self, cron_expr: str) -> str:
        """校验 Cron 表达式并返回标准化结果"""
        return ScheduleEntry.validate_cron(cron_expr)

    def parse_custom_cron(
        self, hour: int, minute: int, day: str = "*", month: str = "*", dow: str = "*"
    ) -> str:
        """解析自定义Cron表达式"""
        return f"{minute} {hour} {day} {month} {dow}"

    def shutdown(self):
        """关闭调度器"""
        for timer in self._timers.values():
            timer.stop()
        self._timers.clear()
        self._running_tasks.clear()
