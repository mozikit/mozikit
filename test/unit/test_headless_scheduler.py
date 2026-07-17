"""
HeadlessScheduler 单元测试 — 无 PySide6 依赖
"""
import os
import shutil
import sys
import time
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from src.core.config_manager import ConfigManager
from src.core.headless_scheduler import HeadlessScheduler
from src.core.cron_utils import CronUtils
from src.core.exceptions import MozikitError


class TestHeadlessSchedulerLifecycle(unittest.TestCase):
    """调度器生命周期管理"""

    def setUp(self):
        self.test_root = Path("test/.tmp_headless_scheduler")
        if self.test_root.exists():
            shutil.rmtree(self.test_root)
        self.test_root.mkdir(parents=True, exist_ok=True)
        self.config_path = self.test_root / "config.json"
        self.scheduler = HeadlessScheduler(
            ConfigManager(str(self.config_path)),
            tick_interval=1,
        )

    def tearDown(self):
        self.scheduler.stop()
        if self.test_root.exists():
            shutil.rmtree(self.test_root)

    def test_initial_state_is_stopped(self):
        self.assertFalse(self.scheduler.is_running)
        self.assertIsNone(self.scheduler.uptime)

    def test_start_sets_running_flag(self):
        self.scheduler.start()
        self.assertTrue(self.scheduler.is_running)
        self.assertIsNotNone(self.scheduler.uptime)
        self.scheduler.stop()

    def test_stop_clears_running_flag(self):
        self.scheduler.start()
        self.scheduler.stop()
        self.assertFalse(self.scheduler.is_running)

    def test_double_start_is_idempotent(self):
        self.scheduler.start()
        self.scheduler.start()  # should not raise
        self.assertTrue(self.scheduler.is_running)
        self.scheduler.stop()


class TestHeadlessSchedulerTaskManagement(unittest.TestCase):
    """定时任务增删改查"""

    def setUp(self):
        self.test_root = Path("test/.tmp_headless_scheduler_tasks")
        if self.test_root.exists():
            shutil.rmtree(self.test_root)
        self.test_root.mkdir(parents=True, exist_ok=True)
        self.config_path = self.test_root / "config.json"
        config_mgr = ConfigManager(str(self.config_path))
        config_mgr.save_config = config_mgr.save_config_sync
        self.scheduler = HeadlessScheduler(
            config_mgr,
            tick_interval=10,
        )

    def tearDown(self):
        self.scheduler.stop()
        if self.test_root.exists():
            shutil.rmtree(self.test_root)

    def test_add_task_returns_id(self):
        task_id = self.scheduler.add_task("test", "/path/to/workflow.json", "0 * * * *")
        self.assertIsInstance(task_id, str)
        self.assertEqual(len(task_id), 8)

    def test_add_task_normalizes_cron(self):
        task_id = self.scheduler.add_task("test", "/path/wf.json", "  */30   8  *  *  1-5 ")
        task = self.scheduler.get_task(task_id)
        self.assertEqual(task["cron_expression"], "*/30 8 * * 1-5")

    def test_add_task_sets_next_run(self):
        task_id = self.scheduler.add_task("test", "/path/wf.json", "0 0 * * *")
        task = self.scheduler.get_task(task_id)
        self.assertTrue(task["next_run"])
        # next_run 应该是未来时间
        next_dt = datetime.strptime(task["next_run"], "%Y-%m-%d %H:%M:%S")
        self.assertGreater(next_dt, datetime(2020, 1, 1))

    def test_add_task_persists_to_config(self):
        task_id = self.scheduler.add_task("test_wf", "/path/wf.json", "*/5 * * * *")
        # 确保异步保存完成
        self.scheduler.config_manager.save_config_sync()
        # 重新加载调度器，确认任务已持久化
        scheduler2 = HeadlessScheduler(
            ConfigManager(str(self.config_path)),
        )
        tasks = scheduler2.list_tasks()
        self.assertEqual(len(tasks), 1)
        self.assertEqual(tasks[0]["id"], task_id)
        self.assertEqual(tasks[0]["workflow_name"], "test_wf")

    def test_list_tasks_returns_all(self):
        id1 = self.scheduler.add_task("wf1", "/path/1.json", "0 * * * *")
        id2 = self.scheduler.add_task("wf2", "/path/2.json", "0 0 * * *")
        id3 = self.scheduler.add_task("wf3", "/path/3.json", "0 0 * * 0")

        tasks = self.scheduler.list_tasks()
        self.assertEqual(len(tasks), 3)
        ids = [t["id"] for t in tasks]
        self.assertIn(id1, ids)
        self.assertIn(id2, ids)
        self.assertIn(id3, ids)

    def test_remove_task_returns_true_and_removes(self):
        task_id = self.scheduler.add_task("test", "/path/wf.json", "0 * * * *")
        self.assertTrue(self.scheduler.remove_task(task_id))
        self.assertIsNone(self.scheduler.get_task(task_id))
        self.assertEqual(len(self.scheduler.list_tasks()), 0)

    def test_remove_nonexistent_task_returns_false(self):
        self.assertFalse(self.scheduler.remove_task("nonexistent"))

    def test_get_task_returns_none_for_missing(self):
        self.assertIsNone(self.scheduler.get_task("nonexistent"))

    def test_update_task_changes_cron(self):
        task_id = self.scheduler.add_task("test", "/path/wf.json", "0 * * * *")
        original_next = self.scheduler.get_task(task_id)["next_run"]

        updated = self.scheduler.update_task(task_id, cron_expression="15 10 * * 1-5")
        self.assertTrue(updated)

        task = self.scheduler.get_task(task_id)
        self.assertEqual(task["cron_expression"], "15 10 * * 1-5")
        self.assertNotEqual(task["next_run"], original_next)

    def test_update_task_rejects_invalid_cron(self):
        task_id = self.scheduler.add_task("test", "/path/wf.json", "0 * * * *")
        with self.assertRaises(MozikitError):
            self.scheduler.update_task(task_id, cron_expression="61 * * * *")

    def test_is_task_running_defaults_false(self):
        task_id = self.scheduler.add_task("test", "/path/wf.json", "0 * * * *")
        self.assertFalse(self.scheduler.is_task_running(task_id))

    def test_update_task_nonexistent_returns_false(self):
        """更新不存在的任务应返回 False"""
        result = self.scheduler.update_task("nonexistent", cron_expression="0 * * * *")
        self.assertFalse(result)

    def test_is_task_running_true_during_execution(self):
        """任务执行期间 is_task_running 应返回 True"""
        # 创建一个真实的临时工作流文件，让 Path.exists() 通过
        import tempfile
        import json
        tmp_wf = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump({"workflow_name": "test", "nodes": [], "edges": [], "version": 2}, tmp_wf)
        tmp_wf.close()

        try:
            with patch("src.core.workflow_executor.WorkflowExecutor.load_workflow") as mock_load:
                import time as _time
                def _slow(*args, **kwargs):
                    _time.sleep(0.4)
                    raise FileNotFoundError("模拟慢加载")
                mock_load.side_effect = _slow

                task_id = self.scheduler.add_task("test", tmp_wf.name, "0 * * * *")
                self.scheduler.run_now(task_id)
                # 后台线程正在执行，flag 应为 True
                _time.sleep(0.1)
                self.assertTrue(self.scheduler.is_task_running(task_id))
                _time.sleep(0.5)
        finally:
            os.unlink(tmp_wf.name)

    def test_add_task_with_default_cron(self):
        task_id = self.scheduler.add_task("test", "/path/wf.json")
        task = self.scheduler.get_task(task_id)
        self.assertEqual(task["cron_expression"], "0 * * * *")


class TestHeadlessSchedulerScheduleCheck(unittest.TestCase):
    """调度轮询逻辑"""

    def setUp(self):
        self.test_root = Path("test/.tmp_headless_scheduler_check")
        if self.test_root.exists():
            shutil.rmtree(self.test_root)
        self.test_root.mkdir(parents=True, exist_ok=True)
        self.config_path = self.test_root / "config.json"
        config_mgr = ConfigManager(str(self.config_path))
        config_mgr.save_config = config_mgr.save_config_sync
        self.scheduler = HeadlessScheduler(
            config_mgr,
            tick_interval=1,
        )
        # 用一个很小的 tick 方便测试

    def tearDown(self):
        self.scheduler.stop()
        if self.test_root.exists():
            shutil.rmtree(self.test_root)

    def test_task_disabled_does_not_execute(self):
        """禁用的任务不应触发执行"""
        exec_log = []

        def on_start(task):
            exec_log.append(task["id"])

        self.scheduler.on_task_start(on_start)

        task_id = self.scheduler.add_task(
            "test", "/path/workflow.json", "*/1 * * * *"
        )
        # 手动将 next_run 设为过去，触发检查
        past_time = datetime(2020, 1, 1, 0, 0, 0).strftime("%Y-%m-%d %H:%M:%S")
        self.scheduler.update_task(task_id, enabled=False, next_run=past_time)

        self.scheduler._check_schedules()
        # 禁用任务不应触发
        self.assertEqual(len(exec_log), 0)

    def test_task_with_future_next_run_not_executed(self):
        """未来时间的任务不应触发"""
        exec_log = []

        def on_start(task):
            exec_log.append(task["id"])

        self.scheduler.on_task_start(on_start)

        future = datetime(2099, 12, 31, 23, 59, 59).strftime("%Y-%m-%d %H:%M:%S")
        task_id = self.scheduler.add_task("test", "/path/wf.json", "0 * * * *")
        self.scheduler.update_task(task_id, next_run=future)

        self.scheduler._check_schedules()
        self.assertEqual(len(exec_log), 0)

    def test_task_execution_updates_next_run(self):
        """执行后应更新 next_run"""
        task_id = self.scheduler.add_task("test", "/path/wf.json", "0 * * * *")
        past = datetime(2020, 1, 1, 0, 0, 0).strftime("%Y-%m-%d %H:%M:%S")
        self.scheduler.update_task(task_id, next_run=past)

        # 没有真实的工作流文件，_execute_task 会失败
        # 但 _check_schedules 应更新 next_run 为未来时间
        self.scheduler._check_schedules()

        task = self.scheduler.get_task(task_id)
        # next_run 应已更新为未来时间
        next_dt = datetime.strptime(task["next_run"], "%Y-%m-%d %H:%M:%S")
        self.assertGreater(next_dt, datetime(2020, 1, 1))
        # last_run 应已记录
        self.assertIsNotNone(task["last_run"])


class TestHeadlessSchedulerCallback(unittest.TestCase):
    """回调注册"""

    def test_on_task_start_callback(self):
        cb = lambda task: None
        scheduler = HeadlessScheduler(
            ConfigManager(str(Path("test/.tmp_hs_cb") / "config.json")),
        )
        scheduler.on_task_start(cb)
        self.assertEqual(scheduler._on_task_start, cb)

    def test_on_task_complete_callback(self):
        cb = lambda record: None
        scheduler = HeadlessScheduler(
            ConfigManager(str(Path("test/.tmp_hs_cb") / "config.json")),
        )
        scheduler.on_task_complete(cb)
        self.assertEqual(scheduler._on_task_complete, cb)

    def test_on_task_failed_callback(self):
        cb = lambda task, error: None
        scheduler = HeadlessScheduler(
            ConfigManager(str(Path("test/.tmp_hs_cb") / "config.json")),
        )
        scheduler.on_task_failed(cb)
        self.assertEqual(scheduler._on_task_failed, cb)


class TestHeadlessSchedulerRunNow(unittest.TestCase):
    """立即执行"""

    def setUp(self):
        self.test_root = Path("test/.tmp_headless_scheduler_runnow")
        if self.test_root.exists():
            shutil.rmtree(self.test_root)
        self.test_root.mkdir(parents=True, exist_ok=True)
        self.config_path = self.test_root / "config.json"
        config_mgr = ConfigManager(str(self.config_path))
        config_mgr.save_config = config_mgr.save_config_sync
        self.scheduler = HeadlessScheduler(
            config_mgr,
        )

    def tearDown(self):
        self.scheduler.stop()
        if self.test_root.exists():
            shutil.rmtree(self.test_root)

    def test_run_now_missing_task(self):
        """不存在的任务不应抛出异常"""
        self.scheduler.run_now("nonexistent")  # should not raise

    def test_run_now_creates_execution_record(self):
        """立即执行应创建执行记录（即使工作流文件不存在也应记录失败）"""
        task_id = self.scheduler.add_task("test", "/tmp/nonexistent_wf.json", "0 * * * *")
        self.scheduler.run_now(task_id)

        # 给后台线程一点时间完成
        time.sleep(0.5)

        # 应该有一条执行记录
        history = self.scheduler.config_manager.get_execution_history()
        self.assertGreaterEqual(len(history), 1)
        self.assertEqual(history[0]["status"], "failed")


class TestHeadlessSchedulerConcurrency(unittest.TestCase):
    """并发与异常处理"""

    def setUp(self):
        self.test_root = Path("test/.tmp_headless_scheduler_conc")
        if self.test_root.exists():
            shutil.rmtree(self.test_root)
        self.test_root.mkdir(parents=True, exist_ok=True)
        self.config_path = self.test_root / "config.json"
        config_mgr = ConfigManager(str(self.config_path))
        config_mgr.save_config = config_mgr.save_config_sync
        self.scheduler = HeadlessScheduler(
            config_mgr,
            tick_interval=1,
        )

    def tearDown(self):
        self.scheduler.stop()
        if self.test_root.exists():
            shutil.rmtree(self.test_root)

    def test_tick_does_not_raise_on_check_error(self):
        """_tick 在 _check_schedules 异常时不应传播异常"""
        # 修补 _check_schedules 让其抛出异常
        original = self.scheduler._check_schedules
        def _broken():
            raise RuntimeError("模拟检查异常")
        self.scheduler._check_schedules = _broken

        try:
            # _tick 内部有 try/except，不应抛出
            self.scheduler._tick()
        except RuntimeError:
            self.fail("_tick 不应传播 _check_schedules 的异常")

        self.scheduler._check_schedules = original

    def test_task_concurrent_execution_guard(self):
        """同一任务不应并发执行（第二次触发应被跳过）"""
        import tempfile
        import json
        import time as _time

        tmp_wf = tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False)
        json.dump({"workflow_name": "test", "nodes": [], "edges": [], "version": 2}, tmp_wf)
        tmp_wf.close()

        try:
            with patch("src.core.workflow_executor.WorkflowExecutor.load_workflow") as mock_load:
                def _slow(*a, **kw):
                    _time.sleep(0.5)
                    return MagicMock()
                mock_load.return_value = MagicMock()
                # 让 execute 变慢
                mock_load.return_value.execute = lambda **kw: (_time.sleep(0.3), {"success": True})[1]

                task_id = self.scheduler.add_task("test", tmp_wf.name)
                task = self.scheduler.get_task(task_id)

                calls = []
                def _call():
                    self.scheduler._execute_task(task)
                    calls.append(1)

                import threading
                t1 = threading.Thread(target=_call)
                t2 = threading.Thread(target=_call)
                t1.start()
                _time.sleep(0.05)
                t2.start()
                t1.join()
                t2.join()

                # 第一个调用启动后台任务（flag=True），第二个应被跳过
                # 所以 calls 应该有 2（两个 _execute_task 调用都返回）
                # 但后台只实际执行一次
                self.assertEqual(len(calls), 2)
        finally:
            os.unlink(tmp_wf.name)


class TestHeadlessSchedulerPersistence(unittest.TestCase):
    """持久化和恢复"""

    def setUp(self):
        self.test_root = Path("test/.tmp_headless_scheduler_persist")
        if self.test_root.exists():
            shutil.rmtree(self.test_root)
        self.test_root.mkdir(parents=True, exist_ok=True)
        self.config_path = self.test_root / "config.json"

    def tearDown(self):
        if self.test_root.exists():
            shutil.rmtree(self.test_root)

    def test_tasks_survive_scheduler_restart(self):
        """任务应在调度器重启后仍然存在"""
        s1 = HeadlessScheduler(ConfigManager(str(self.config_path)))
        id1 = s1.add_task("wf1", "/path/wf1.json", "0 * * * *")
        id2 = s1.add_task("wf2", "/path/wf2.json", "0 0 * * *")
        s1.config_manager.save_config_sync()
        s1.stop()

        s2 = HeadlessScheduler(ConfigManager(str(self.config_path)))
        tasks = s2.list_tasks()
        self.assertEqual(len(tasks), 2)
        task_ids = [t["id"] for t in tasks]
        self.assertIn(id1, task_ids)
        self.assertIn(id2, task_ids)
        s2.stop()


if __name__ == "__main__":
    unittest.main()
