"""
CLI 命令单元测试 — 使用 Typer CliRunner
"""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from typer.testing import CliRunner

from src.cli import app
from src.core.exceptions import ErrorCode, MozikitError


class TestCLIAppStructure(unittest.TestCase):
    """CLI 应用结构"""

    def setUp(self):
        self.runner = CliRunner()

    def test_help_contains_all_commands(self):
        result = self.runner.invoke(app, ["--help"])
        self.assertEqual(result.exit_code, 0)
        for cmd in ["run", "schedule", "env", "node", "config", "workflow", "serve"]:
            self.assertIn(cmd, result.output)

    def test_run_help_shows_options(self):
        result = self.runner.invoke(app, ["run", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("WORKFLOW_PATH", result.output)
        self.assertIn("--input", result.output)
        self.assertIn("--output", result.output)
        self.assertIn("--verbose", result.output)

    def test_schedule_help_shows_commands(self):
        result = self.runner.invoke(app, ["schedule", "--help"])
        self.assertEqual(result.exit_code, 0)
        for cmd in ["list", "add", "remove", "run", "status", "daemon"]:
            self.assertIn(cmd, result.output)

    def test_env_help_shows_commands(self):
        result = self.runner.invoke(app, ["env", "--help"])
        self.assertEqual(result.exit_code, 0)
        for cmd in ["list", "create", "remove"]:
            self.assertIn(cmd, result.output)

    def test_node_help_shows_commands(self):
        result = self.runner.invoke(app, ["node", "--help"])
        self.assertEqual(result.exit_code, 0)
        for cmd in ["list", "info"]:
            self.assertIn(cmd, result.output)

    def test_config_help_shows_commands(self):
        result = self.runner.invoke(app, ["config", "--help"])
        self.assertEqual(result.exit_code, 0)
        for cmd in ["show", "set"]:
            self.assertIn(cmd, result.output)

    def test_help_subcommand_shows_top_level_help(self):
        """help 子命令应显示与 --help 相同的内容"""
        result_help = self.runner.invoke(app, ["help"])
        self.assertEqual(result_help.exit_code, 0)
        self.assertIn("Usage:", result_help.output)
        self.assertIn("Commands", result_help.output)  # rich table header

    def test_workflow_help_shows_commands(self):
        result = self.runner.invoke(app, ["workflow", "--help"])
        self.assertEqual(result.exit_code, 0)
        for cmd in ["list", "validate", "describe", "stats",
                     "create", "delete", "rename",
                     "add-node", "remove-node", "update-node",
                     "connect", "disconnect"]:
            self.assertIn(cmd, result.output)


@patch("src.cli._load_workflow")
class TestCLIRunCommand(unittest.TestCase):
    """run 命令"""

    def setUp(self):
        self.runner = CliRunner()

    def test_run_no_args_shows_error(self, mock_load):
        result = self.runner.invoke(app, ["run"])
        self.assertNotEqual(result.exit_code, 0)

    def test_run_with_nonexistent_path_shows_error(self, mock_load):
        mock_load.side_effect = SystemExit(1)
        with patch("src.cli.Path.exists", return_value=False):
            result = self.runner.invoke(app, ["run", "/nonexistent/wf.json"])
            self.assertNotEqual(result.exit_code, 0)

    def test_run_with_mock_workflow(self, mock_load):
        """模拟加载成功、执行成功的场景"""
        mock_executor = MagicMock()
        mock_executor.workflow_name = "test_wf"
        mock_executor.nodes = [MagicMock(), MagicMock()]
        mock_executor.prepare_environment.return_value = True
        mock_executor.execute.return_value = {
            "success": True,
            "run_id": "test-001",
            "workflow_name": "test_wf",
            "duration_ms": 100,
            "nodes": [],
            "final_context": {},
        }
        mock_load.return_value = mock_executor

        with patch("src.cli.Path.exists", return_value=True):
            with patch("src.cli.Path.is_file", return_value=True):
                result = self.runner.invoke(
                    app, ["run", "/fake/workflow.json", "--verbose"]
                )
                self.assertEqual(result.exit_code, 0)
                self.assertIn("工作流执行成功", result.output)

    def test_run_with_input_data(self, mock_load):
        """指定 --input JSON 数据"""
        mock_executor = MagicMock()
        mock_executor.workflow_name = "test_wf"
        mock_executor.nodes = []
        mock_executor.prepare_environment.return_value = True
        mock_executor.execute.return_value = {
            "success": True,
            "run_id": "test-002",
        }
        mock_load.return_value = mock_executor

        with patch("src.cli.Path.exists", return_value=True):
            with patch("src.cli.Path.is_file", return_value=True):
                result = self.runner.invoke(
                    app,
                    [
                        "run", "/fake/workflow.json",
                        "--input", '{"key": "value"}',
                    ],
                )
                self.assertEqual(result.exit_code, 0)
                # 验证 input 被传递
                _, kwargs = mock_executor.execute.call_args
                self.assertEqual(kwargs["initial_data"], {"key": "value"})

    def test_run_with_args_option(self, mock_load):
        """指定 --args key=value 参数"""
        mock_executor = MagicMock()
        mock_executor.workflow_name = "test_wf"
        mock_executor.nodes = []
        mock_executor.prepare_environment.return_value = True
        mock_executor.execute.return_value = {"success": True}
        mock_load.return_value = mock_executor

        with patch("src.cli.Path.exists", return_value=True):
            with patch("src.cli.Path.is_file", return_value=True):
                result = self.runner.invoke(
                    app,
                    [
                        "run", "/fake/workflow.json",
                        "--args", "name=alice",
                        "--args", "count=42",
                    ],
                )
                self.assertEqual(result.exit_code, 0)
                _, kwargs = mock_executor.execute.call_args
                self.assertEqual(kwargs["initial_data"], {"name": "alice", "count": "42"})

    def test_run_with_output_file(self, mock_load):
        """指定 --output 保存结果"""
        mock_executor = MagicMock()
        mock_executor.workflow_name = "test_wf"
        mock_executor.nodes = []
        mock_executor.prepare_environment.return_value = True
        mock_executor.execute.return_value = {"success": True, "data": "result"}
        mock_load.return_value = mock_executor

        with patch("src.cli.Path.exists", return_value=True):
            with patch("src.cli.Path.is_file", return_value=True):
                with self.runner.isolated_filesystem():
                    result = self.runner.invoke(
                        app,
                        [
                            "run", "/fake/workflow.json",
                            "--output", "output.json",
                        ],
                    )
                    self.assertEqual(result.exit_code, 0)
                    self.assertTrue(Path("output.json").exists())
                    with open("output.json") as f:
                        data = json.load(f)
                    self.assertEqual(data["success"], True)

    def test_run_execution_failure(self, mock_load):
        """工作流执行失败场景"""
        mock_executor = MagicMock()
        mock_executor.workflow_name = "test_wf"
        mock_executor.nodes = []
        mock_executor.prepare_environment.return_value = True
        mock_executor.execute.return_value = {
            "success": False,
            "error": "Something went wrong",
        }
        mock_load.return_value = mock_executor

        with patch("src.cli.Path.exists", return_value=True):
            with patch("src.cli.Path.is_file", return_value=True):
                result = self.runner.invoke(
                    app, ["run", "/fake/workflow.json"]
                )
                self.assertNotEqual(result.exit_code, 0)
                self.assertIn("执行失败", result.output)

    def test_run_environment_preparation_failure(self, mock_load):
        """环境准备失败场景"""
        mock_executor = MagicMock()
        mock_executor.workflow_name = "test_wf"
        mock_executor.nodes = [MagicMock()]
        mock_executor.prepare_environment.return_value = False
        mock_load.return_value = mock_executor

        with patch("src.cli.Path.exists", return_value=True):
            with patch("src.cli.Path.is_file", return_value=True):
                result = self.runner.invoke(
                    app, ["run", "/fake/workflow.json"]
                )
                self.assertNotEqual(result.exit_code, 0)
                self.assertIn("环境准备失败", result.output)

    def test_run_input_invalid_content(self, mock_load):
        """--input 既不是 JSON 也不是 key=value 应报错"""
        mock_executor = MagicMock()
        mock_executor.workflow_name = "test_wf"
        mock_executor.nodes = []
        mock_load.return_value = mock_executor

        with patch("src.cli.Path.exists", return_value=True):
            with patch("src.cli.Path.is_file", return_value=True):
                result = self.runner.invoke(
                    app, ["run", "/fake/wf.json", "--input", "not-json-not-kv"]
                )
                self.assertNotEqual(result.exit_code, 0)
                self.assertIn("无法解析", result.output)

    def test_run_executor_raises_exception(self, mock_load):
        """executor.execute() 抛出异常应报错"""
        mock_executor = MagicMock()
        mock_executor.workflow_name = "test_wf"
        mock_executor.nodes = []
        mock_executor.prepare_environment.return_value = True
        mock_executor.execute.side_effect = RuntimeError("unexpected error")
        mock_load.return_value = mock_executor

        with patch("src.cli.Path.exists", return_value=True):
            with patch("src.cli.Path.is_file", return_value=True):
                result = self.runner.invoke(
                    app, ["run", "/fake/wf.json"]
                )
                self.assertNotEqual(result.exit_code, 0)
                self.assertIn("异常", result.output)


class TestCLIConfigCommand(unittest.TestCase):
    """config 命令"""

    def setUp(self):
        self.runner = CliRunner()

    @patch("src.cli.ConfigManager")
    def test_config_show(self, mock_mgr_cls):
        mock_mgr = MagicMock()
        mock_mgr.config = {"theme": "dark", "lang": "zh"}
        mock_mgr.get_execution_stats.return_value = {
            "total_runs": 0, "successful_runs": 0, "failed_runs": 0, "success_rate": 0.0
        }
        mock_mgr_cls.return_value = mock_mgr

        result = self.runner.invoke(app, ["config", "show"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("theme", result.output)
        self.assertIn("dark", result.output)

    @patch("src.cli.ConfigManager")
    def test_config_set_string(self, mock_mgr_cls):
        mock_mgr = MagicMock()
        mock_mgr.config = {}  # 真实 dict
        mock_mgr_cls.return_value = mock_mgr

        result = self.runner.invoke(app, ["config", "set", "theme", "light"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("配置已更新", result.output)
        self.assertEqual(mock_mgr.config["theme"], "light")
        mock_mgr.save_config_sync.assert_called_once()

    @patch("src.cli.ConfigManager")
    def test_config_set_json_number(self, mock_mgr_cls):
        mock_mgr = MagicMock()
        mock_mgr.config = {}  # 真实 dict
        mock_mgr_cls.return_value = mock_mgr

        result = self.runner.invoke(app, ["config", "set", "timeout", "300"])
        self.assertEqual(result.exit_code, 0)
        # 数字字符串应解析为整数
        self.assertEqual(mock_mgr.config["timeout"], 300)

    @patch("src.cli.ConfigManager")
    def test_config_set_unparseable_value(self, mock_mgr_cls):
        """无法解析为 JSON 的值应回退为字符串"""
        mock_mgr = MagicMock()
        mock_mgr.config = {}
        mock_mgr_cls.return_value = mock_mgr

        result = self.runner.invoke(
            app, ["config", "set", "name", "hello world"]
        )
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(mock_mgr.config["name"], "hello world")
        mock_mgr.save_config_sync.assert_called_once()


class TestCLIScheduleCommand(unittest.TestCase):
    """schedule 命令"""

    def setUp(self):
        self.runner = CliRunner()

    @patch("src.cli.HeadlessScheduler")
    def test_schedule_list_empty(self, mock_sched_cls):
        mock_sched = MagicMock()
        mock_sched.list_tasks.return_value = []
        mock_sched_cls.return_value = mock_sched

        result = self.runner.invoke(app, ["schedule", "list"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("没有定时任务", result.output)

    @patch("src.cli.HeadlessScheduler")
    def test_schedule_list_with_tasks(self, mock_sched_cls):
        mock_sched = MagicMock()
        mock_sched.list_tasks.return_value = [
            {
                "id": "abc123",
                "workflow_name": "test_wf",
                "cron_expression": "0 * * * *",
                "enabled": True,
                "last_run": None,
                "next_run": "2026-05-16 00:00:00",
            }
        ]
        mock_sched_cls.return_value = mock_sched

        result = self.runner.invoke(app, ["schedule", "list"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("abc123", result.output)
        self.assertIn("test_wf", result.output)

    @patch("src.cli.HeadlessScheduler")
    def test_schedule_add(self, mock_sched_cls):
        mock_sched = MagicMock()
        mock_sched.add_task.return_value = "new-id-123"
        mock_sched_cls.return_value = mock_sched

        with patch("src.cli.Path.exists", return_value=True):
            result = self.runner.invoke(
                app,
                [
                    "schedule", "add",
                    "/path/to/workflow.json",
                    "--cron", "*/5 * * * *",
                    "--name", "my-task",
                ],
            )
            self.assertEqual(result.exit_code, 0)
            self.assertIn("new-id-123", result.output)
            mock_sched.add_task.assert_called_once_with(
                "my-task", "/path/to/workflow.json", "*/5 * * * *"
            )

    @patch("src.cli.HeadlessScheduler")
    def test_schedule_add_with_default_name(self, mock_sched_cls):
        """未指定名称时使用文件 stem"""
        mock_sched = MagicMock()
        mock_sched.add_task.return_value = "id-456"
        mock_sched_cls.return_value = mock_sched

        with patch("src.cli.Path.exists", return_value=True):
            with patch("src.cli.Path.stem", "my_workflow"):
                result = self.runner.invoke(
                    app,
                    ["schedule", "add", "/path/to/my_workflow.json"],
                )
                self.assertEqual(result.exit_code, 0)
                mock_sched.add_task.assert_called_once_with(
                    "my_workflow", "/path/to/my_workflow.json", "0 * * * *"
                )

    def test_schedule_add_nonexistent_path(self):
        """schedule add 时文件不存在应报错"""
        with patch("src.cli.HeadlessScheduler"), patch("src.cli.Path.exists", return_value=False):
            result = self.runner.invoke(
                app, ["schedule", "add", "/nonexistent/wf.json"]
            )
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("不存在", result.output)

    @patch("src.cli.HeadlessScheduler")
    def test_schedule_add_invalid_cron(self, mock_sched_cls):
        """schedule add 时无效 cron 应报错"""
        mock_sched = MagicMock()
        mock_sched.add_task.side_effect = MozikitError(ErrorCode.INVALID_CRON_EXPRESSION, "无效的 Cron 表达式")
        mock_sched_cls.return_value = mock_sched

        with patch("src.cli.Path.exists", return_value=True):
            result = self.runner.invoke(
                app,
                ["schedule", "add", "/path/to/wf.json", "--cron", "not-a-cron"],
            )
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("无效", result.output)

    @patch("src.cli.HeadlessScheduler")
    def test_schedule_remove(self, mock_sched_cls):
        mock_sched = MagicMock()
        mock_sched.remove_task.return_value = True
        mock_sched_cls.return_value = mock_sched

        result = self.runner.invoke(app, ["schedule", "remove", "task-123"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("已删除", result.output)
        mock_sched.remove_task.assert_called_once_with("task-123")

    @patch("src.cli.HeadlessScheduler")
    def test_schedule_remove_nonexistent(self, mock_sched_cls):
        mock_sched = MagicMock()
        mock_sched.remove_task.return_value = False
        mock_sched_cls.return_value = mock_sched

        result = self.runner.invoke(app, ["schedule", "remove", "missing"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("不存在", result.output)

    @patch("src.cli.HeadlessScheduler")
    def test_schedule_status(self, mock_sched_cls):
        mock_sched = MagicMock()
        mock_sched.list_tasks.return_value = [
            {"id": "a", "enabled": True},
            {"id": "b", "enabled": True},
            {"id": "c", "enabled": False},
        ]
        mock_sched_cls.return_value = mock_sched

        result = self.runner.invoke(app, ["schedule", "status"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("3", result.output)
        self.assertIn("2", result.output)

    @patch("src.cli.HeadlessScheduler")
    def test_schedule_run(self, mock_sched_cls):
        mock_sched = MagicMock()
        mock_sched.get_task.return_value = {"id": "task-1", "workflow_name": "test"}
        mock_sched_cls.return_value = mock_sched

        result = self.runner.invoke(app, ["schedule", "run", "task-1"])
        self.assertEqual(result.exit_code, 0)
        mock_sched.run_now.assert_called_once_with("task-1")

    @patch("src.cli.HeadlessScheduler")
    def test_schedule_run_missing_task(self, mock_sched_cls):
        mock_sched = MagicMock()
        mock_sched.get_task.return_value = None
        mock_sched_cls.return_value = mock_sched

        result = self.runner.invoke(app, ["schedule", "run", "missing"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("不存在", result.output)

    @patch("src.cli.HeadlessScheduler")
    def test_schedule_status_no_tasks(self, mock_sched_cls):
        """没有定时任务时 status 应显示 0"""
        mock_sched = MagicMock()
        mock_sched.list_tasks.return_value = []
        mock_sched_cls.return_value = mock_sched

        result = self.runner.invoke(app, ["schedule", "status"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("0", result.output)


class TestCLINodeCommand(unittest.TestCase):
    """node 命令"""

    def setUp(self):
        self.runner = CliRunner()

    @patch("src.cli.get_registry")
    def test_node_list_empty(self, mock_reg):
        mock_registry = MagicMock()
        mock_registry.get_all_nodes.return_value = []
        mock_reg.return_value = mock_registry

        result = self.runner.invoke(app, ["node", "list"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("没有可用节点", result.output)

    @patch("src.cli.get_registry")
    def test_node_list_with_nodes(self, mock_reg):
        mock_registry = MagicMock()
        mock_registry.get_all_nodes.return_value = [
            {"name": "HTTP Request", "category": "network", "description": "Send HTTP", "version": "1.0"},
            {"name": "File Read", "category": "io", "description": "Read file", "version": "2.0"},
        ]
        mock_reg.return_value = mock_registry

        result = self.runner.invoke(app, ["node", "list"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("HTTP Request", result.output)
        self.assertIn("File Read", result.output)
        self.assertIn("network", result.output)

    @patch("src.cli.get_registry")
    def test_node_info(self, mock_reg):
        mock_registry = MagicMock()
        mock_registry.get_node_info.return_value = {"name": "HTTP Request", "source": "official"}
        mock_registry.get_all_nodes.return_value = [
            {
                "name": "HTTP Request",
                "type": "http_request",
                "category": "network",
                "description": "Send HTTP request",
                "version": "1.0",
                "input_schema": [{"name": "url", "type": "string"}],
                "output_schema": [{"name": "response", "type": "object"}],
            }
        ]
        mock_reg.return_value = mock_registry

        result = self.runner.invoke(app, ["node", "info", "HTTP Request"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("HTTP Request", result.output)
        self.assertIn("network", result.output)
        self.assertIn("url", result.output)
        self.assertIn("response", result.output)

    @patch("src.cli.get_registry")
    def test_node_list_registry_error(self, mock_reg):
        """registry 异常时 node list 应报错"""
        mock_reg.side_effect = RuntimeError("registry broken")
        result = self.runner.invoke(app, ["node", "list"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("无法加载", result.output)

    @patch("src.cli.get_registry")
    def test_node_info_registry_error(self, mock_reg):
        """registry 异常时 node info 应报错"""
        mock_reg.side_effect = RuntimeError("registry broken")
        result = self.runner.invoke(app, ["node", "info", "SomeNode"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("无法加载", result.output)


class TestCLIWorkflowCommand(unittest.TestCase):
    """workflow 命令"""

    def setUp(self):
        self.runner = CliRunner()

    def test_workflow_list_no_dir(self):
        with patch("src.cli.Path.exists", return_value=False):
            result = self.runner.invoke(app, ["workflow", "list"])
            self.assertEqual(result.exit_code, 0)
            self.assertIn("没有找到", result.output)

    @patch("src.cli._load_workflow")
    def test_workflow_validate(self, mock_load):
        mock_executor = MagicMock()
        mock_executor.workflow_name = "test_wf"
        mock_executor.nodes = [MagicMock(), MagicMock()]
        mock_executor.edges = [MagicMock()]
        mock_executor._topological_sort.return_value = ["node1", "node2"]
        mock_load.return_value = mock_executor

        result = self.runner.invoke(app, ["workflow", "validate", "/fake/wf.json"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("格式有效", result.output)
        self.assertIn("test_wf", result.output)
        self.assertIn("2", result.output)

    @patch("src.cli._load_workflow")
    def test_workflow_describe(self, mock_load):
        from collections import namedtuple
        Edge = namedtuple("Edge", ["from_node", "from_port", "to_node", "to_port"])

        mock_node = MagicMock()
        mock_node.node_id = "n1"
        mock_node.node_type = "variable_assign"
        mock_node.label = "Set X"

        mock_node2 = MagicMock()
        mock_node2.node_id = "n2"
        mock_node2.node_type = "variable_calc"
        mock_node2.label = None  # 测试 label fallback

        mock_executor = MagicMock()
        mock_executor.workflow_name = "detailed_wf"
        mock_executor.nodes = {"n1": mock_node, "n2": mock_node2}
        mock_executor.edges = [
            Edge("n1", "output", "n2", "input"),
        ]
        mock_load.return_value = mock_executor

        result = self.runner.invoke(app, ["workflow", "describe", "/fake/wf.json"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("detailed_wf", result.output)
        self.assertIn("n1", result.output)
        self.assertIn("variable_assign", result.output)
        self.assertIn("n2", result.output)

    @patch("src.cli._load_workflow")
    def test_workflow_validate_topological_error(self, mock_load):
        mock_executor = MagicMock()
        mock_executor.workflow_name = "broken_wf"
        mock_executor.nodes = [MagicMock()]
        mock_executor.edges = []
        mock_executor._topological_sort.side_effect = MozikitError(ErrorCode.WORKFLOW_CYCLE_DETECTED, "循环依赖检测")
        mock_load.return_value = mock_executor

        result = self.runner.invoke(app, ["workflow", "validate", "/fake/wf.json"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("失败", result.output)

    def test_workflow_list_corrupted_json(self):
        """workflow list 遇到损坏的 JSON 应跳过"""
        with self.runner.isolated_filesystem():
            wf_dir = Path("workflows")
            wf_dir.mkdir()
            (wf_dir / "workflow.json").write_text("{bad json}")
            result = self.runner.invoke(app, ["workflow", "list"])
            self.assertEqual(result.exit_code, 0)
            self.assertIn("已保存的工作流", result.output)

    def test_workflow_list_empty_dir(self):
        """workflows 目录存在但为空"""
        with self.runner.isolated_filesystem():
            Path("workflows").mkdir()
            result = self.runner.invoke(app, ["workflow", "list"])
            self.assertEqual(result.exit_code, 0)
            self.assertIn("没有找到", result.output)


class TestCLIEnvCommand(unittest.TestCase):
    """env 命令"""

    def setUp(self):
        self.runner = CliRunner()

    @patch("src.cli.UVManager")
    def test_env_list(self, mock_uv_cls):
        mock_uv = MagicMock()
        mock_uv.list_environments.return_value = [
            {"name": "myenv", "python_version": "3.12", "path": "/tmp/.venvs/myenv"},
        ]
        mock_uv_cls.return_value = mock_uv

        result = self.runner.invoke(app, ["env", "list"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("myenv", result.output)

    @patch("src.cli.UVManager")
    def test_env_create(self, mock_uv_cls):
        mock_uv = MagicMock()
        mock_uv_cls.return_value = mock_uv

        result = self.runner.invoke(app, ["env", "create", "testenv"])
        self.assertEqual(result.exit_code, 0)
        mock_uv.create_environment.assert_called_once_with("testenv", "3.12")

    @patch("src.cli.UVManager")
    def test_env_remove(self, mock_uv_cls):
        mock_uv = MagicMock()
        mock_uv_cls.return_value = mock_uv

        result = self.runner.invoke(app, ["env", "remove", "testenv"])
        self.assertEqual(result.exit_code, 0)
        mock_uv.remove_environment.assert_called_once_with("testenv")

    @patch("src.cli.UVManager")
    def test_env_create_exception(self, mock_uv_cls):
        """创建环境时 UVManager 异常应报错"""
        mock_uv = MagicMock()
        mock_uv.create_environment.side_effect = RuntimeError("creation failed")
        mock_uv_cls.return_value = mock_uv

        result = self.runner.invoke(app, ["env", "create", "testenv"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("创建环境失败", result.output)

    @patch("src.cli.UVManager")
    def test_env_remove_exception(self, mock_uv_cls):
        """删除环境时 UVManager 异常应报错"""
        mock_uv = MagicMock()
        mock_uv.remove_environment.side_effect = RuntimeError("removal failed")
        mock_uv_cls.return_value = mock_uv

        result = self.runner.invoke(app, ["env", "remove", "testenv"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("删除环境失败", result.output)


class TestCLIServeCommand(unittest.TestCase):
    """serve 命令"""

    def setUp(self):
        self.runner = CliRunner()

    def test_serve_missing_dependency(self):
        """缺少 fastapi/uvicorn 时应给出友好提示"""
        with patch.dict("sys.modules", {"fastapi": None, "uvicorn": None}, clear=False):
            result = self.runner.invoke(app, ["serve"])
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("fastapi", result.output)
            self.assertIn("uvicorn", result.output)


if __name__ == "__main__":
    unittest.main()
