import os
import shutil
import sys
import unittest
from datetime import datetime
from pathlib import Path

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import QCoreApplication

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from src.core.config_manager import ConfigManager
from src.core.exceptions import MozikitError
from src.core.scheduler_manager import ScheduleEntry, SchedulerManager


@pytest.mark.qt
class TestScheduleEntry(unittest.TestCase):
    def test_minutely_cron_supports_step_expression(self):
        next_run = ScheduleEntry.format_next_run(
            "*/1 * * * *", datetime(2026, 4, 25, 18, 27, 30)
        )

        self.assertEqual(next_run, datetime(2026, 4, 25, 18, 28, 0))

    def test_weekly_cron_uses_sunday_as_zero(self):
        next_run = ScheduleEntry.format_next_run(
            "0 0 * * 0", datetime(2026, 4, 25, 18, 27, 30)
        )

        self.assertEqual(next_run, datetime(2026, 4, 26, 0, 0, 0))

    def test_monthly_cron_respects_day_of_month(self):
        next_run = ScheduleEntry.format_next_run(
            "0 0 1 * *", datetime(2026, 4, 25, 18, 27, 30)
        )

        self.assertEqual(next_run, datetime(2026, 5, 1, 0, 0, 0))

    def test_daily_cron_rounds_to_minute_boundary(self):
        next_run = ScheduleEntry.format_next_run(
            "0 0 * * *", datetime(2026, 4, 25, 18, 27, 30)
        )

        self.assertEqual(next_run, datetime(2026, 4, 26, 0, 0, 0))

    def test_validate_cron_normalizes_whitespace(self):
        normalized = ScheduleEntry.validate_cron("  */15   *  *  *  1-5  ")

        self.assertEqual(normalized, "*/15 * * * 1-5")

    def test_validate_cron_rejects_invalid_field_count(self):
        with self.assertRaisesRegex(MozikitError, "无效的 Cron 表达式"):
            ScheduleEntry.validate_cron("0 0 * *")

    def test_validate_cron_rejects_invalid_range(self):
        with self.assertRaisesRegex(MozikitError, "无效的 Cron 字段范围"):
            ScheduleEntry.validate_cron("0 24 * * *")


@pytest.mark.qt
class TestSchedulerManager(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QCoreApplication.instance() or QCoreApplication([])

    def setUp(self):
        self.test_root = Path("test/.tmp_scheduler_manager")
        if self.test_root.exists():
            shutil.rmtree(self.test_root)
        self.test_root.mkdir(parents=True, exist_ok=True)

        self.config_path = self.test_root / "config.json"
        self.manager = SchedulerManager(ConfigManager(str(self.config_path)))
        self.manager._scheduler_timer.stop()

    def _flush_save(self):
        """等待异步 save_config 完成，避免 tearDown 时竞争。"""
        if hasattr(self, 'manager') and hasattr(self.manager, '_config_manager'):
            self.manager._config_manager.save_config_sync()

    def tearDown(self):
        self.manager.shutdown()
        # 多次调用 flush 确保所有后台异步写入完成
        self._flush_save()
        import time
        time.sleep(0.1)
        self._flush_save()
        if self.test_root.exists():
            shutil.rmtree(self.test_root)

    def test_add_task_normalizes_custom_cron_before_persisting(self):
        task_id = self.manager.add_task(
            "demo", "workflows/demo/workflow.json", "  */30   8  *  *  1-5 "
        )

        task = self.manager.get_task(task_id)
        self.assertEqual(task["cron_expression"], "*/30 8 * * 1-5")
        self.assertTrue(task["next_run"])

    def test_update_task_recomputes_next_run_for_custom_cron(self):
        task_id = self.manager.add_task(
            "demo", "workflows/demo/workflow.json", "0 0 * * *"
        )
        original_next_run = self.manager.get_task(task_id)["next_run"]

        updated = self.manager.update_task(task_id, cron_expression="15 10 * * 1-5")

        self.assertTrue(updated)
        task = self.manager.get_task(task_id)
        self.assertEqual(task["cron_expression"], "15 10 * * 1-5")
        self.assertNotEqual(task["next_run"], original_next_run)

    def test_update_task_rejects_invalid_custom_cron(self):
        task_id = self.manager.add_task(
            "demo", "workflows/demo/workflow.json", "0 0 * * *"
        )

        with self.assertRaisesRegex(MozikitError, "无效的 Cron 字段范围"):
            self.manager.update_task(task_id, cron_expression="61 * * * *")


if __name__ == "__main__":
    unittest.main()
