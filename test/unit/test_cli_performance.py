"""
CLI 性能/负载测试
测试大量节点渲染、快速配置写入、调度器轮询等场景的响应时间。
"""
import json
import os
import sys
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from typer.testing import CliRunner
from src.cli import app


class TestCLIRunPerformance(unittest.TestCase):
    """run 命令性能测试"""

    def setUp(self):
        self.runner = CliRunner()

    @patch("src.cli._load_workflow")
    def test_run_large_workflow_throughput(self, mock_load):
        """100 节点工作流应在 2 秒内完成（纯 mock，无实际执行）"""
        mock_executor = MagicMock()
        mock_executor.workflow_name = "large_wf"
        mock_executor.nodes = [MagicMock() for _ in range(100)]
        mock_executor.prepare_environment.return_value = True
        mock_executor.execute.return_value = {
            "success": True,
            "duration_ms": 50,
            "workflow_name": "large_wf",
        }
        mock_load.return_value = mock_executor

        with patch("src.cli.Path.exists", return_value=True), \
             patch("src.cli.Path.is_file", return_value=True):
            start = time.perf_counter()
            result = self.runner.invoke(app, ["run", "/fake/wf.json", "--json"])
            elapsed = time.perf_counter() - start

            self.assertEqual(result.exit_code, 0)
            self.assertLess(elapsed, 2.0,
                f"100-node workflow took {elapsed:.2f}s, expected < 2.0s")
            self.assertIn("success", result.output)

    @patch("src.cli._load_workflow")
    def test_run_json_flag_does_not_degrade(self, mock_load):
        """--json 模式不应比普通模式慢超过 0.5s"""
        mock_executor = MagicMock()
        mock_executor.workflow_name = "wf"
        mock_executor.nodes = [MagicMock()]
        mock_executor.prepare_environment.return_value = True
        mock_executor.execute.return_value = {"success": True}

        mock_load.return_value = mock_executor

        with patch("src.cli.Path.exists", return_value=True), \
             patch("src.cli.Path.is_file", return_value=True):

            t1 = time.perf_counter()
            self.runner.invoke(app, ["run", "/fake/wf.json"])
            normal_time = time.perf_counter() - t1

            t2 = time.perf_counter()
            self.runner.invoke(app, ["run", "/fake/wf.json", "--json"])
            json_time = time.perf_counter() - t2

            self.assertLess(abs(json_time - normal_time), 0.5,
                f"JSON mode ({json_time:.3f}s) vs normal ({normal_time:.3f}s) diff too large")


class TestCLIListPerformance(unittest.TestCase):
    """列表渲染性能测试"""

    def setUp(self):
        self.runner = CliRunner()

    @patch("src.cli.get_registry")
    def test_node_list_500_nodes(self, mock_reg):
        """500 个节点应在 1 秒内完成列表渲染"""
        mock_registry = MagicMock()
        mock_registry.get_all_nodes.return_value = [
            {
                "name": f"Node_{i}",
                "category": "test",
                "source": "NodeSource.OFFICIAL",
                "description": f"test node {i}",
                "version": "1.0",
            }
            for i in range(500)
        ]
        mock_reg.return_value = mock_registry

        start = time.perf_counter()
        result = self.runner.invoke(app, ["node", "list"])
        elapsed = time.perf_counter() - start

        self.assertEqual(result.exit_code, 0)
        self.assertLess(elapsed, 1.0,
            f"500-node list took {elapsed:.2f}s, expected < 1.0s")
        self.assertIn("Node_499", result.output)
        self.assertIn("Node_0", result.output)


class TestCLIConfigPerformance(unittest.TestCase):
    """config 命令性能测试"""

    def setUp(self):
        self.runner = CliRunner()

    def test_config_set_100_times_sequential(self):
        """100 次连续 config set 应在 3 秒内完成"""
        start = time.perf_counter()
        count = 0
        for i in range(100):
            with patch("src.cli.ConfigManager") as mock_cfg_cls:
                mock_mgr = MagicMock()
                mock_mgr.config = {}
                mock_cfg_cls.return_value = mock_mgr

                result = self.runner.invoke(
                    app, ["config", "set", f"key_{i}", str(i)]
                )
                if result.exit_code == 0:
                    count += 1

        elapsed = time.perf_counter() - start
        self.assertEqual(count, 100, f"Only {count}/100 config set succeeded")
        self.assertLess(elapsed, 3.0,
            f"100 config set calls took {elapsed:.2f}s, expected < 3.0s")


class TestCLISchedulePerformance(unittest.TestCase):
    """schedule 命令性能测试"""

    def setUp(self):
        self.runner = CliRunner()

    @patch("src.cli.HeadlessScheduler")
    def test_schedule_list_100_tasks(self, mock_sched_cls):
        """100 个定时任务列表应在 1 秒内完成渲染"""
        mock_sched = MagicMock()
        mock_sched.list_tasks.return_value = [
            {
                "id": f"task-{i:04d}",
                "workflow_name": f"wf_{i}",
                "cron_expression": "0 * * * *",
                "enabled": i % 2 == 0,
                "last_run": None,
                "next_run": "2026-06-01 00:00:00",
            }
            for i in range(100)
        ]
        mock_sched_cls.return_value = mock_sched

        start = time.perf_counter()
        result = self.runner.invoke(app, ["schedule", "list"])
        elapsed = time.perf_counter() - start

        self.assertEqual(result.exit_code, 0)
        self.assertLess(elapsed, 1.0,
            f"100-task list took {elapsed:.2f}s, expected < 1.0s")
        self.assertIn("wf_0", result.output)
        self.assertIn("wf_99", result.output)


if __name__ == "__main__":
    unittest.main()
