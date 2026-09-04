"""
main.py CLI 模式检测单元测试
"""
import os
import sys
import unittest
from unittest.mock import patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from main import _is_cli_mode


class TestCLIModeDetection(unittest.TestCase):
    """CLI 模式检测逻辑"""

    def test_no_args_returns_false(self):
        with patch("sys.argv", ["main.py"]):
            self.assertFalse(_is_cli_mode())

    def test_dash_dash_run_returns_true(self):
        with patch("sys.argv", ["main.py", "--run", "workflow.json"]):
            self.assertTrue(_is_cli_mode())

    def test_dash_dash_cli_returns_true(self):
        with patch("sys.argv", ["main.py", "--cli"]):
            self.assertTrue(_is_cli_mode())

    def test_dash_dash_help_returns_true(self):
        with patch("sys.argv", ["main.py", "--help"]):
            self.assertTrue(_is_cli_mode())

    def test_dash_h_returns_true(self):
        with patch("sys.argv", ["main.py", "-h"]):
            self.assertTrue(_is_cli_mode())

    def test_run_subcommand_returns_true(self):
        with patch("sys.argv", ["main.py", "run", "workflow.json"]):
            self.assertTrue(_is_cli_mode())

    def test_schedule_subcommand_returns_true(self):
        with patch("sys.argv", ["main.py", "schedule", "list"]):
            self.assertTrue(_is_cli_mode())

    def test_config_subcommand_returns_true(self):
        with patch("sys.argv", ["main.py", "config", "show"]):
            self.assertTrue(_is_cli_mode())

    def test_env_subcommand_returns_true(self):
        with patch("sys.argv", ["main.py", "env", "list"]):
            self.assertTrue(_is_cli_mode())

    def test_node_subcommand_returns_true(self):
        with patch("sys.argv", ["main.py", "node", "list"]):
            self.assertTrue(_is_cli_mode())

    def test_workflow_subcommand_returns_true(self):
        with patch("sys.argv", ["main.py", "workflow", "validate", "wf.json"]):
            self.assertTrue(_is_cli_mode())

    def test_serve_subcommand_returns_true(self):
        with patch("sys.argv", ["main.py", "serve"]):
            self.assertTrue(_is_cli_mode())

    def test_runtime_daemon_subcommand_returns_true(self):
        with patch("sys.argv", ["Mozikit.exe", "runtime", "daemon"]):
            self.assertTrue(_is_cli_mode())

    def test_unknown_command_returns_false(self):
        """未知命令应返回 False（走 GUI 模式并让 PySide6 报错）"""
        with patch("sys.argv", ["main.py", "unknown_cmd"]):
            self.assertFalse(_is_cli_mode())

    def test_qt_style_option_returns_false(self):
        """Qt 风格的 - 开头选项不应触发 CLI 模式"""
        with patch("sys.argv", ["main.py", "-style", "fusion"]):
            self.assertFalse(_is_cli_mode())

    def test_qt_platform_option_returns_false(self):
        with patch("sys.argv", ["main.py", "-platform", "windows"]):
            self.assertFalse(_is_cli_mode())

    def test_dash_dash_run_with_other_args(self):
        with patch("sys.argv", ["main.py", "--run", "--verbose"]):
            self.assertTrue(_is_cli_mode())

    def test_only_dash_dash_style(self):
        """只有 Qt 风格选项时不触发 CLI"""
        with patch("sys.argv", ["main.py", "--style", "Fusion"]):
            self.assertFalse(_is_cli_mode())

    def test_mixed_qt_and_cli(self):
        """同时包含 Qt 选项和 CLI 子命令"""
        with patch("sys.argv", ["main.py", "--style", "Fusion", "run", "wf.json"]):
            self.assertTrue(_is_cli_mode())


if __name__ == "__main__":
    unittest.main()
