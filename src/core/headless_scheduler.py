"""
无头调度器 — 不依赖 PySide6 的定时任务管理
与 GUI 版 SchedulerManager 共用 ConfigManager 持久化格式，可直接读写同一份任务列表。
"""
from __future__ import annotations

import threading
import uuid
import time
from datetime import datetime, timedelta
from typing import Callable, Optional

from .config_manager import ConfigManager
from .cron_utils import CronUtils
from .log_manager import get_logger
from .workflow_run_dispatcher import WorkflowRunDispatcher

logger = get_logger("headless_scheduler")


class HeadlessScheduler:
    """
    基于 threading.Timer 的轻量调度器。

    与 SchedulerManager 的区别：
    - 不需要 QApplication 事件循环
    - 每 tick_interval 秒轮询一次任务表
    - 适合 CLI、守护进程、CI/CD 等无头场景
    """

    def __init__(
        self,
        config_manager: Optional[ConfigManager] = None,
        tick_interval: int = 10,
    ):
        """
        Args:
            config_manager: 配置管理器实例，不传则新建
            tick_interval: 轮询间隔（秒），默认 10
        """
        self.config_manager = config_manager or ConfigManager()
        self.dispatcher = WorkflowRunDispatcher(config_manager=self.config_manager)
        self.tick_interval = tick_interval

        self._running = False
        self._started_at: Optional[datetime] = None
        self._timer: Optional[threading.Timer] = None
        self._lock = threading.Lock()
        self._running_tasks: dict[str, bool] = {}
        self._on_task_start: Optional[Callable] = None
        self._on_task_complete: Optional[Callable] = None
        self._on_task_failed: Optional[Callable] = None

    # ── 生命周期 ───────────────────────────────────

    def start(self):
        """启动调度器（后台线程轮询）"""
        with self._lock:
            if self._running:
                logger.warning("调度器已在运行中")
                return
            self._running = True
            self._started_at = datetime.now()

        logger.info(
            "调度器已启动 (tick=%ds, config=%s)",
            self.tick_interval,
            self.config_manager.config_file,
        )
        self._tick()

    def stop(self):
        """停止调度器"""
        with self._lock:
            self._running = False
            if self._timer:
                self._timer.cancel()
                self._timer = None
        logger.info("调度器已停止")

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def uptime(self) -> Optional[timedelta]:
        if self._started_at:
            return datetime.now() - self._started_at
        return None

    # ── 回调注册 ──────────────────────────────────

    def on_task_start(self, callback: Callable):
        self._on_task_start = callback

    def on_task_complete(self, callback: Callable):
        self._on_task_complete = callback

    def on_task_failed(self, callback: Callable):
        self._on_task_failed = callback

    # ── 任务管理 ───────────────────────────────────

    def add_task(
        self,
        workflow_name: str,
        workflow_path: str,
        cron_expr: str = "0 * * * *",
    ) -> str:
        """添加定时任务

        Args:
            workflow_name: 工作流名称
            workflow_path: 工作流文件路径
            cron_expr: Cron 表达式

        Returns:
            任务 ID
        """
        cron_expr = CronUtils.validate_cron(cron_expr)
        task_id = str(uuid.uuid4())[:8]
        next_run = CronUtils.format_next_run(cron_expr)

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
        logger.info("定时任务已添加: %s [%s]", task_id, cron_expr)
        return task_id

    def remove_task(self, task_id: str) -> bool:
        """删除定时任务"""
        result = self.config_manager.delete_scheduled_task(task_id)
        if result:
            with self._lock:
                self._running_tasks.pop(task_id, None)
            logger.info("定时任务已删除: %s", task_id)
        return result

    def update_task(self, task_id: str, **updates) -> bool:
        """更新定时任务"""
        if "cron_expression" in updates:
            normalized = CronUtils.validate_cron(updates["cron_expression"])
            next_run = CronUtils.format_next_run(normalized)
            updates["cron_expression"] = normalized
            updates["next_run"] = next_run.strftime("%Y-%m-%d %H:%M:%S")
        return self.config_manager.update_scheduled_task(task_id, updates)

    def list_tasks(self) -> list[dict]:
        """列出所有定时任务"""
        return self.config_manager.get_scheduled_tasks()

    def get_task(self, task_id: str) -> Optional[dict]:
        """获取指定任务"""
        return self.config_manager.get_scheduled_task(task_id)

    def run_now(self, task_id: str):
        """立即执行指定任务"""
        task = self.get_task(task_id)
        if not task:
            logger.error("任务不存在: %s", task_id)
            return
        logger.info("立即执行任务: %s (%s)", task_id, task.get("workflow_name"))
        self._execute_task(task)

    def is_task_running(self, task_id: str) -> bool:
        return self._running_tasks.get(task_id, False)

    # ── 内部实现 ───────────────────────────────────

    def _tick(self):
        """单次轮询"""
        with self._lock:
            if not self._running:
                return

        try:
            self._check_schedules()
        except Exception:
            logger.exception("调度轮询异常")

        with self._lock:
            if self._running:
                self._timer = threading.Timer(self.tick_interval, self._tick)
                self._timer.daemon = True
                self._timer.start()

    def _check_schedules(self):
        """检查所有任务是否需要触发"""
        now = datetime.now()
        current_time = now.strftime("%Y-%m-%d %H:%M:%S")

        for task in self.config_manager.get_scheduled_tasks():
            if not task.get("enabled", True):
                continue

            next_run = task.get("next_run", "")
            if not next_run:
                continue

            if next_run <= current_time:
                self._execute_task(task)

                next_time = CronUtils.format_next_run(
                    task.get("cron_expression", "0 * * * *")
                )
                task["next_run"] = next_time.strftime("%Y-%m-%d %H:%M:%S")
                self.config_manager.update_scheduled_task(
                    task["id"],
                    {"next_run": task["next_run"], "last_run": current_time},
                )

    def _execute_task(self, task: dict):
        """后台执行工作流"""
        task_id = task.get("id")
        workflow_path = task.get("workflow_path", "")

        with self._lock:
            if self._running_tasks.get(task_id, False):
                logger.warning("任务 %s 正在运行，跳过本次触发", task_id)
                return
            self._running_tasks[task_id] = True

        if self._on_task_start:
            try:
                self._on_task_start(task)
            except Exception:
                pass

        def _run():
            try:
                logger.info("执行定时任务: %s (%s)", task_id, workflow_path)
                result = self.dispatcher.dispatch(
                    workflow_path,
                    trigger_type="scheduled",
                    workflow_name=task.get("workflow_name"),
                )
                report = result.report
                record = result.record

                if report.get("success"):
                    logger.info("定时任务完成: %s", task_id)
                    if self._on_task_complete:
                        try:
                            self._on_task_complete(record)
                        except Exception:
                            pass
                else:
                    error = report.get("error", "执行失败")
                    logger.error("定时任务失败: %s — %s", task_id, error)
                    if self._on_task_failed:
                        try:
                            self._on_task_failed(task, error)
                        except Exception:
                            pass

            except Exception as e:
                logger.exception("定时任务异常: %s", task_id)
                if self._on_task_failed:
                    try:
                        self._on_task_failed(task, str(e))
                    except Exception:
                        pass
            finally:
                with self._lock:
                    self._running_tasks[task_id] = False

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
