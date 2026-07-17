"""
CLI 新命令单元测试 — 仅覆盖新增/增强的命令
"""
import json
import os
import sys
import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, call

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from typer.testing import CliRunner

from src.cli import app
from src.core.code_safety import SafetyReviewResult
from src.core.exceptions import ErrorCode, MozikitError


def _json_from_output(result) -> dict:
    """从 CLI 输出中提取 JSON（Rich 可能会添加 ANSI 换行/控制字符）"""
    text = result.output
    # 去除 ANSI 转义序列
    text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
    text = re.sub(r"\x1b\][0-9;]*\x07", "", text)
    # 合并所有行（Rich 可能因终端宽度换行）
    text = "".join(text.splitlines())
    return json.loads(text)


# ===================================================================
# 1. TestCLIAppStructure — 验证新增命令出现在 --help 中
# ===================================================================

class TestCLIAppStructure(unittest.TestCase):
    """CLI 应用结构 — 验证新增命令"""

    @staticmethod
    def _clean_output(output: str) -> str:
        """去除 rich 添加的 ANSI 转义码，便于字符串匹配。"""
        return re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", output)

    def setUp(self):
        self.runner = CliRunner()

    def test_help_contains_all_commands(self):
        result = self.runner.invoke(app, ["--help"])
        self.assertEqual(result.exit_code, 0)
        for cmd in ["run", "schedule", "env", "node", "config", "workflow", "serve"]:
            self.assertIn(cmd, result.output)

    def test_run_help_shows_json_option(self):
        """run --help 应包含 --json / -j 选项"""
        result = self.runner.invoke(app, ["run", "--help"])
        self.assertEqual(result.exit_code, 0)
        output = self._clean_output(result.output)
        self.assertIn("--json", output)
        self.assertIn("-j", output)

    def test_schedule_help_shows_update_command(self):
        """schedule --help 应包含 update"""
        result = self.runner.invoke(app, ["schedule", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("update", result.output)
        for cmd in ["list", "add", "remove", "run", "status", "daemon"]:
            self.assertIn(cmd, result.output)

    def test_env_help_shows_new_commands(self):
        """env --help 应包含 status 和 set-mirror"""
        result = self.runner.invoke(app, ["env", "--help"])
        self.assertEqual(result.exit_code, 0)
        for cmd in ["list", "create", "remove", "status", "set-mirror"]:
            self.assertIn(cmd, result.output)

    def test_node_help_shows_new_commands(self):
        """node --help 应包含新增子命令"""
        result = self.runner.invoke(app, ["node", "--help"])
        self.assertEqual(result.exit_code, 0)
        for cmd in ["list", "info", "create", "delete", "export", "import",
                     "generate", "check-safety", "repo"]:
            self.assertIn(cmd, result.output)

    def test_node_repo_help_shows_commands(self):
        """node repo --help 应包含子命令"""
        result = self.runner.invoke(app, ["node", "repo", "--help"])
        self.assertEqual(result.exit_code, 0)
        for cmd in ["list", "check-updates", "install"]:
            self.assertIn(cmd, result.output)

    def test_config_help_shows_github_commands(self):
        """config --help 应包含 github-login 和 github-logout"""
        result = self.runner.invoke(app, ["config", "--help"])
        self.assertEqual(result.exit_code, 0)
        for cmd in ["show", "set", "github-login", "github-logout"]:
            self.assertIn(cmd, result.output)


# ===================================================================
# 2. run --json flag
# ===================================================================

@patch("src.cli._load_workflow")
class TestCLIRunJsonCommand(unittest.TestCase):
    """run --json 命令"""

    def setUp(self):
        self.runner = CliRunner()

    def _make_executor(self, nodes_count=2, **overrides):
        mock_exe = MagicMock()
        mock_exe.workflow_name = "test_wf"
        mock_exe.nodes = [MagicMock() for _ in range(nodes_count)]
        mock_exe.prepare_environment.return_value = True
        report = {
            "success": True,
            "run_id": "test-001",
            "workflow_name": "test_wf",
            "duration_ms": 1234,
            "nodes": [],
            "final_context": {},
            **overrides,
        }
        mock_exe.execute.return_value = report
        return mock_exe

    def _patch_path(self):
        return patch("src.cli.Path.exists", return_value=True), patch("src.cli.Path.is_file", return_value=True)

    def test_run_json_flag_output(self, mock_load):
        """--json 输出应包含 JSON 报告字段"""
        mock_load.return_value = self._make_executor()
        with patch("src.cli.Path.exists", return_value=True), \
             patch("src.cli.Path.is_file", return_value=True):
            result = self.runner.invoke(app, ["run", "/fake/wf.json", "--json"])
        self.assertEqual(result.exit_code, 0)
        data = _json_from_output(result)
        self.assertIn("success", data)
        self.assertIn("workflow", data)
        self.assertIn("duration_ms", data)
        self.assertIn("completed_nodes", data)
        self.assertIn("total_nodes", data)
        self.assertTrue(data["success"])

    def test_run_json_flag_failure(self, mock_load):
        """--json 模式执行失败应返回 success: false"""
        mock_load.return_value = self._make_executor(success=False, error="some error")
        with patch("src.cli.Path.exists", return_value=True), \
             patch("src.cli.Path.is_file", return_value=True):
            result = self.runner.invoke(app, ["run", "/fake/wf.json", "--json"])
        self.assertNotEqual(result.exit_code, 0)
        data = _json_from_output(result)
        self.assertFalse(data["success"])
        self.assertIn("some error", data.get("error", ""))

    def test_run_json_env_failure(self, mock_load):
        """--json 模式环境准备失败应返回 JSON 错误"""
        mock_exe = self._make_executor()
        mock_exe.prepare_environment.return_value = False
        mock_load.return_value = mock_exe
        with patch("src.cli.Path.exists", return_value=True), \
             patch("src.cli.Path.is_file", return_value=True):
            result = self.runner.invoke(app, ["run", "/fake/wf.json", "--json"])
        self.assertNotEqual(result.exit_code, 0)
        data = _json_from_output(result)
        self.assertFalse(data["success"])
        self.assertIn("环境准备失败", data.get("error", ""))

    def test_run_json_executor_exception(self, mock_load):
        """--json 模式 executor 抛出异常应返回 JSON"""
        mock_exe = self._make_executor()
        mock_exe.execute.side_effect = RuntimeError("boom")
        mock_load.return_value = mock_exe
        with patch("src.cli.Path.exists", return_value=True), \
             patch("src.cli.Path.is_file", return_value=True):
            result = self.runner.invoke(app, ["run", "/fake/wf.json", "--json"])
        self.assertNotEqual(result.exit_code, 0)
        data = _json_from_output(result)
        self.assertFalse(data["success"])
        self.assertIn("boom", data.get("error", ""))

    def test_run_json_on_node_log_callback(self, mock_load):
        """--json --verbose 模式下 on_node_log callback 应传入 executor.execute"""
        mock_exe = self._make_executor()
        mock_load.return_value = mock_exe
        with patch("src.cli.Path.exists", return_value=True), \
             patch("src.cli.Path.is_file", return_value=True):
            self.runner.invoke(app, ["run", "/fake/wf.json", "--json", "--verbose"])
        _, kwargs = mock_exe.execute.call_args
        self.assertIn("on_node_log", kwargs)
        self.assertTrue(callable(kwargs["on_node_log"]))

    def test_run_json_with_input(self, mock_load):
        """--json 配合 --input 仍能正确传入 initial_data"""
        mock_exe = self._make_executor()
        mock_load.return_value = mock_exe
        with patch("src.cli.Path.exists", return_value=True), \
             patch("src.cli.Path.is_file", return_value=True):
            result = self.runner.invoke(app, [
                "run", "/fake/wf.json", "--json",
                "--input", '{"key": "value"}',
            ])
        self.assertEqual(result.exit_code, 0)
        _, kwargs = mock_exe.execute.call_args
        self.assertEqual(kwargs["initial_data"], {"key": "value"})


# ===================================================================
# 3. schedule update
# ===================================================================

@patch("src.cli.HeadlessScheduler")
class TestCLIScheduleUpdateCommand(unittest.TestCase):
    """schedule update 命令"""

    def setUp(self):
        self.runner = CliRunner()

    def _make_task(self, **overrides):
        return {
            "id": "task-123",
            "workflow_name": "my_task",
            "cron_expression": "0 * * * *",
            "enabled": True,
            **overrides,
        }

    def test_schedule_update_cron(self, mock_sched_cls):
        """--cron 应调用 update_task 更新 cron_expression"""
        mock_sched = MagicMock()
        mock_sched.get_task.return_value = self._make_task()
        mock_sched.update_task.return_value = True
        mock_sched_cls.return_value = mock_sched

        result = self.runner.invoke(app, [
            "schedule", "update", "task-123", "--cron", "*/5 * * * *",
        ])
        self.assertEqual(result.exit_code, 0)
        mock_sched.update_task.assert_called_once_with(
            "task-123", cron_expression="*/5 * * * *",
        )

    def test_schedule_update_name(self, mock_sched_cls):
        """--name 应调用 update_task 更新 workflow_name"""
        mock_sched = MagicMock()
        mock_sched.get_task.return_value = self._make_task()
        mock_sched.update_task.return_value = True
        mock_sched_cls.return_value = mock_sched

        result = self.runner.invoke(app, [
            "schedule", "update", "task-123", "--name", "newname",
        ])
        self.assertEqual(result.exit_code, 0)
        mock_sched.update_task.assert_called_once_with(
            "task-123", workflow_name="newname",
        )

    def test_schedule_update_enabled(self, mock_sched_cls):
        """--enabled/--disabled 应更新 enabled 字段"""
        mock_sched = MagicMock()
        mock_sched.get_task.return_value = self._make_task()
        mock_sched.update_task.return_value = True
        mock_sched_cls.return_value = mock_sched

        result = self.runner.invoke(app, [
            "schedule", "update", "task-123", "--disabled",
        ])
        self.assertEqual(result.exit_code, 0)
        mock_sched.update_task.assert_called_once_with(
            "task-123", enabled=False,
        )

    def test_schedule_update_missing_task(self, mock_sched_cls):
        """任务不存在时应报错"""
        mock_sched = MagicMock()
        mock_sched.get_task.return_value = None
        mock_sched_cls.return_value = mock_sched

        result = self.runner.invoke(app, [
            "schedule", "update", "nonexistent", "--cron", "*/5 * * * *",
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("不存在", result.output)

    def test_schedule_update_no_changes(self, mock_sched_cls):
        """未提供任何选项时应有提示"""
        mock_sched = MagicMock()
        mock_sched.get_task.return_value = self._make_task()
        mock_sched_cls.return_value = mock_sched

        result = self.runner.invoke(app, [
            "schedule", "update", "task-123",
        ])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("未提供", result.output)
        mock_sched.update_task.assert_not_called()

    def test_schedule_update_all_options(self, mock_sched_cls):
        """同时指定多个选项时应一次调用 update_task 合并"""
        mock_sched = MagicMock()
        mock_sched.get_task.return_value = self._make_task()
        mock_sched.update_task.return_value = True
        mock_sched_cls.return_value = mock_sched

        result = self.runner.invoke(app, [
            "schedule", "update", "task-123",
            "--name", "newname",
            "--cron", "0 0 * * *",
            "--enabled",
        ])
        self.assertEqual(result.exit_code, 0)
        mock_sched.update_task.assert_called_once_with(
            "task-123",
            workflow_name="newname",
            cron_expression="0 0 * * *",
            enabled=True,
        )

    def test_schedule_update_failure(self, mock_sched_cls):
        """update_task 返回 False 时应报错"""
        mock_sched = MagicMock()
        mock_sched.get_task.return_value = self._make_task()
        mock_sched.update_task.return_value = False
        mock_sched_cls.return_value = mock_sched

        result = self.runner.invoke(app, [
            "schedule", "update", "task-123", "--cron", "*/5 * * * *",
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("更新失败", result.output)


# ===================================================================
# 4. env status
# ===================================================================

@patch("src.cli.UVManager")
class TestCLIEnvStatusCommand(unittest.TestCase):
    """env status 命令"""

    def setUp(self):
        self.runner = CliRunner()

    def test_env_status_installed(self, mock_uv_cls):
        """UV 已安装时应显示 ✓"""
        mock_uv = MagicMock()
        mock_uv.check_uv_installed.return_value = True
        mock_uv.get_preferred_uv_path.return_value = "/usr/bin/uv"
        mock_uv.get_current_mirror.return_value = ""
        mock_uv.find_uv_installations.return_value = ["/usr/bin/uv"]
        mock_uv.list_environments.return_value = []
        mock_uv_cls.return_value = mock_uv

        result = self.runner.invoke(app, ["env", "status"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("已安装", result.output)
        self.assertIn("✓", result.output)

    def test_env_status_not_installed(self, mock_uv_cls):
        """UV 未安装时应显示 ✗"""
        mock_uv = MagicMock()
        mock_uv.check_uv_installed.return_value = False
        mock_uv.get_preferred_uv_path.return_value = None
        mock_uv.get_current_mirror.return_value = ""
        mock_uv.find_uv_installations.return_value = []
        mock_uv_cls.return_value = mock_uv

        result = self.runner.invoke(app, ["env", "status"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("已安装", result.output)
        self.assertIn("✗", result.output)

    def test_env_status_with_mirror(self, mock_uv_cls):
        """设置了镜像时应显示镜像地址"""
        mock_uv = MagicMock()
        mock_uv.check_uv_installed.return_value = True
        mock_uv.get_preferred_uv_path.return_value = "/usr/bin/uv"
        mock_uv.get_current_mirror.return_value = "https://pypi.tuna.tsinghua.edu.cn/simple"
        mock_uv.find_uv_installations.return_value = ["/usr/bin/uv"]
        mock_uv.list_environments.return_value = []
        mock_uv_cls.return_value = mock_uv

        result = self.runner.invoke(app, ["env", "status"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("镜像", result.output)
        self.assertIn("tuna.tsinghua", result.output)

    def test_env_status_with_environments(self, mock_uv_cls):
        """存在虚拟环境时应列出"""
        mock_uv = MagicMock()
        mock_uv.check_uv_installed.return_value = True
        mock_uv.get_preferred_uv_path.return_value = "/usr/bin/uv"
        mock_uv.get_current_mirror.return_value = ""
        mock_uv.find_uv_installations.return_value = ["/usr/bin/uv"]
        mock_uv.list_environments.return_value = [
            {"name": "myenv", "python_version": "3.12", "path": "/tmp/.venvs/myenv"},
        ]
        mock_uv_cls.return_value = mock_uv

        result = self.runner.invoke(app, ["env", "status"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("myenv", result.output)
        self.assertIn("3.12", result.output)

    def test_env_status_no_uv_path(self, mock_uv_cls):
        """未找到 UV 路径时应显示 '未找到'"""
        mock_uv = MagicMock()
        mock_uv.check_uv_installed.return_value = True
        mock_uv.get_preferred_uv_path.return_value = None
        mock_uv.get_current_mirror.return_value = ""
        mock_uv.find_uv_installations.return_value = []
        mock_uv.list_environments.return_value = []
        mock_uv_cls.return_value = mock_uv

        result = self.runner.invoke(app, ["env", "status"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("未找到", result.output)


# ===================================================================
# 5. env set-mirror
# ===================================================================

@patch("src.cli.UVManager")
class TestCLIEnvSetMirrorCommand(unittest.TestCase):
    """env set-mirror 命令"""

    def setUp(self):
        self.runner = CliRunner()

    def test_env_set_mirror_success(self, mock_uv_cls):
        """设置镜像成功时应提示已设置"""
        mock_uv = MagicMock()
        mock_uv_cls.return_value = mock_uv

        url = "https://pypi.tuna.tsinghua.edu.cn/simple"
        result = self.runner.invoke(app, ["env", "set-mirror", url])
        self.assertEqual(result.exit_code, 0)
        mock_uv.set_custom_mirror.assert_called_once_with(url)
        self.assertIn("镜像已设置", result.output)

    def test_env_set_mirror_failure(self, mock_uv_cls):
        """设置镜像失败时应报错"""
        mock_uv = MagicMock()
        mock_uv.set_custom_mirror.side_effect = RuntimeError("network error")
        mock_uv_cls.return_value = mock_uv

        result = self.runner.invoke(app, [
            "env", "set-mirror", "https://invalid.example.com/simple",
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("错误", result.output)
        self.assertIn("network error", result.output)


# ===================================================================
# 6. node create
# ===================================================================
# CustomNodeManager 在 _get_custom_mgr() 中懒加载:
#   from src.core.custom_node_manager import CustomNodeManager
# → 在定义模块（src.core.custom_node_manager）处打补丁

@patch("src.cli.get_registry")
@patch("src.core.custom_node_manager.CustomNodeManager")
class TestCLINodeCreateCommand(unittest.TestCase):
    """node create 命令"""

    def setUp(self):
        self.runner = CliRunner()

    def test_node_create_success(self, mock_custom_mgr_cls, mock_reg):
        """创建成功时应显示成功消息并注册节点"""
        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_mgr = MagicMock()
        mock_node_def = MagicMock()
        mock_node_def.name = "MyNode"
        mock_node_def.node_type = "custom_my_node_123"
        mock_mgr.create_node.return_value = mock_node_def
        mock_custom_mgr_cls.return_value = mock_mgr

        result = self.runner.invoke(app, [
            "node", "create", "MyNode", "--desc", "test description",
        ])
        self.assertEqual(result.exit_code, 0)
        mock_mgr.create_node.assert_called_once_with("MyNode", "test description", "自定义")
        mock_registry.register_external_node.assert_called_once_with(mock_node_def)
        self.assertIn("节点已创建", result.output)

    def test_node_create_failure(self, mock_custom_mgr_cls, mock_reg):
        """create_node 返回 None 时应报错"""
        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_mgr = MagicMock()
        mock_mgr.create_node.return_value = None
        mock_custom_mgr_cls.return_value = mock_mgr

        result = self.runner.invoke(app, [
            "node", "create", "MyNode",
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("创建失败", result.output)

    def test_node_create_exception(self, mock_custom_mgr_cls, mock_reg):
        """create_node 抛出异常时应报错"""
        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_mgr = MagicMock()
        mock_mgr.create_node.side_effect = MozikitError(ErrorCode.NODE_ALREADY_EXISTS, "duplicate node")
        mock_custom_mgr_cls.return_value = mock_mgr

        result = self.runner.invoke(app, [
            "node", "create", "MyNode",
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("duplicate node", result.output)

    def test_node_create_with_custom_category(self, mock_custom_mgr_cls, mock_reg):
        """应支持 --category 参数"""
        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_mgr = MagicMock()
        mock_node_def = MagicMock()
        mock_node_def.name = "MyNode"
        mock_node_def.node_type = "custom_my_node"
        mock_mgr.create_node.return_value = mock_node_def
        mock_custom_mgr_cls.return_value = mock_mgr

        result = self.runner.invoke(app, [
            "node", "create", "MyNode", "--category", "数据处理",
        ])
        self.assertEqual(result.exit_code, 0)
        mock_mgr.create_node.assert_called_once_with("MyNode", "", "数据处理")


# ===================================================================
# 7. node delete
# ===================================================================

@patch("src.cli.get_registry")
@patch("src.core.custom_node_manager.CustomNodeManager")
class TestCLINodeDeleteCommand(unittest.TestCase):
    """node delete 命令"""

    def setUp(self):
        self.runner = CliRunner()

    def test_node_delete_success(self, mock_custom_mgr_cls, mock_reg):
        """删除成功时应注销节点"""
        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_mgr = MagicMock()
        mock_mgr.delete_node.return_value = True
        mock_custom_mgr_cls.return_value = mock_mgr

        result = self.runner.invoke(app, ["node", "delete", "custom_test_123"])
        self.assertEqual(result.exit_code, 0)
        mock_mgr.delete_node.assert_called_once_with("custom_test_123")
        mock_registry.unregister_node.assert_called_once_with("custom_test_123")
        self.assertIn("已删除", result.output)

    def test_node_delete_nonexistent(self, mock_custom_mgr_cls, mock_reg):
        """删除不存在的节点时应报错"""
        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_mgr = MagicMock()
        mock_mgr.delete_node.return_value = False
        mock_custom_mgr_cls.return_value = mock_mgr

        result = self.runner.invoke(app, ["node", "delete", "nonexistent"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("不存在", result.output)

    def test_node_delete_exception(self, mock_custom_mgr_cls, mock_reg):
        """delete_node 抛出异常时应报错"""
        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_mgr = MagicMock()
        mock_mgr.delete_node.side_effect = PermissionError("permission denied")
        mock_custom_mgr_cls.return_value = mock_mgr

        result = self.runner.invoke(app, ["node", "delete", "custom_test"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("permission denied", result.output)


# ===================================================================
# 8. node export
# ===================================================================

@patch("src.cli.get_registry")
@patch("src.core.custom_node_manager.CustomNodeManager")
class TestCLINodeExportCommand(unittest.TestCase):
    """node export 命令"""

    def setUp(self):
        self.runner = CliRunner()

    def test_node_export_success(self, mock_custom_mgr_cls, mock_reg):
        """导出成功时应提示"""
        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_mgr = MagicMock()
        mock_mgr.export_node.return_value = True
        mock_custom_mgr_cls.return_value = mock_mgr

        result = self.runner.invoke(app, [
            "node", "export", "custom_test", "/tmp/output.zip",
        ])
        self.assertEqual(result.exit_code, 0)
        mock_mgr.export_node.assert_called_once_with(
            "custom_test", "/tmp/output.zip", all_versions=False,
        )
        self.assertIn("已导出", result.output)

    def test_node_export_failure(self, mock_custom_mgr_cls, mock_reg):
        """导出失败时应报错"""
        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_mgr = MagicMock()
        mock_mgr.export_node.return_value = False
        mock_custom_mgr_cls.return_value = mock_mgr

        result = self.runner.invoke(app, [
            "node", "export", "custom_test", "/tmp/output.zip",
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("导出失败", result.output)

    def test_node_export_all_versions(self, mock_custom_mgr_cls, mock_reg):
        """--all 标志应传递 all_versions=True"""
        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_mgr = MagicMock()
        mock_mgr.export_node.return_value = True
        mock_custom_mgr_cls.return_value = mock_mgr

        result = self.runner.invoke(app, [
            "node", "export", "custom_test", "/tmp/output.zip", "--all",
        ])
        self.assertEqual(result.exit_code, 0)
        mock_mgr.export_node.assert_called_once_with(
            "custom_test", "/tmp/output.zip", all_versions=True,
        )

    def test_node_export_exception(self, mock_custom_mgr_cls, mock_reg):
        """export_node 抛出异常时应报错"""
        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_mgr = MagicMock()
        mock_mgr.export_node.side_effect = OSError("disk full")
        mock_custom_mgr_cls.return_value = mock_mgr

        result = self.runner.invoke(app, [
            "node", "export", "custom_test", "/tmp/output.zip",
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("disk full", result.output)


# ===================================================================
# 9. node import
# ===================================================================

@patch("src.cli.get_registry")
@patch("src.core.custom_node_manager.CustomNodeManager")
class TestCLINodeImportCommand(unittest.TestCase):
    """node import 命令"""

    def setUp(self):
        self.runner = CliRunner()

    def test_node_import_success(self, mock_custom_mgr_cls, mock_reg):
        """导入成功时应重新加载外部节点"""
        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_mgr = MagicMock()
        mock_mgr.import_node.return_value = "imported_node_type"
        mock_custom_mgr_cls.return_value = mock_mgr

        result = self.runner.invoke(app, [
            "node", "import", "/tmp/node_package.zip",
        ])
        self.assertEqual(result.exit_code, 0)
        mock_mgr.import_node.assert_called_once_with("/tmp/node_package.zip")
        mock_registry._load_external_nodes.assert_called_once()
        self.assertIn("已导入", result.output)
        self.assertIn("imported_node_type", result.output)

    def test_node_import_failure(self, mock_custom_mgr_cls, mock_reg):
        """import_node 返回 None 时应报错"""
        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_mgr = MagicMock()
        mock_mgr.import_node.return_value = None
        mock_custom_mgr_cls.return_value = mock_mgr

        result = self.runner.invoke(app, [
            "node", "import", "/tmp/bad_package.zip",
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("导入失败", result.output)

    def test_node_import_exception(self, mock_custom_mgr_cls, mock_reg):
        """import_node 抛出异常时应报错"""
        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_mgr = MagicMock()
        mock_mgr.import_node.side_effect = MozikitError(ErrorCode.IMPORT_FAILED, "invalid zip format")
        mock_custom_mgr_cls.return_value = mock_mgr

        result = self.runner.invoke(app, [
            "node", "import", "/tmp/bad_package.zip",
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("invalid zip format", result.output)


# ===================================================================
# 10. node generate
# ===================================================================
# AINodeGenerationService / CustomNodeManager 在命令函数体中懒加载:
#   from src.core.ai_node_generator import AINodeGenerationService
#   from src.core.custom_node_manager import CustomNodeManager
# → 在各自定义模块处打补丁

@patch("src.cli.get_registry")
@patch("src.core.custom_node_manager.CustomNodeManager")
@patch("src.core.ai_node_generator.AINodeGenerationService")
@patch("src.cli.ConfigManager")
class TestCLINodeGenerateCommand(unittest.TestCase):
    """node generate 命令"""

    def setUp(self):
        self.runner = CliRunner()

    def _make_safe_result(self):
        """创建通过安全审查的生成结果"""
        result = MagicMock()
        result.name = "GeneratedNode"
        result.description = "An AI-generated node"
        result.source_code = "print('hello')"
        result.config_schema = {}
        result.dependencies = ["requests"]
        result.category = "AI 生成"
        result.version = "1.0.0"
        safety = MagicMock()
        safety.risk_level = "low"
        safety.high_risks = []
        safety.all_risks.return_value = []
        result.safety_review = safety
        return result

    def _make_high_risk_result(self):
        """创建安全审查不通过的生成结果"""
        result = self._make_safe_result()
        safety = MagicMock()
        safety.risk_level = "high"
        safety.high_risks = ["使用了 os.system"]
        safety.all_risks.return_value = ["使用了 os.system"]
        result.safety_review = safety
        return result

    def test_node_generate_no_api_key(self, mock_cm_cls, mock_ai_cls, mock_custom_cls, mock_reg):
        """未配置 AI 接口时应报错"""
        mock_cm = MagicMock()
        mock_cm.get_ai_settings.return_value = {"api_key": ""}
        mock_cm_cls.return_value = mock_cm

        result = self.runner.invoke(app, [
            "node", "generate", "MyNode", "--desc", "test",
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("未配置 AI 接口", result.output)

    def test_node_generate_success(self, mock_cm_cls, mock_ai_cls, mock_custom_cls, mock_reg):
        """生成成功时应创建节点并注册"""
        mock_cm = MagicMock()
        mock_cm.get_ai_settings.return_value = {
            "api_key": "sk-test", "model": "gpt-4",
        }
        mock_cm_cls.return_value = mock_cm

        mock_service = MagicMock()
        mock_service.generate_node.return_value = self._make_safe_result()
        mock_ai_cls.return_value = mock_service

        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_mgr = MagicMock()
        mock_node_def = MagicMock()
        mock_node_def.name = "GeneratedNode"
        mock_node_def.node_type = "custom_generated_node_123"
        mock_mgr.create_generated_node.return_value = mock_node_def
        mock_custom_cls.return_value = mock_mgr

        result = self.runner.invoke(app, [
            "node", "generate", "MyNode", "--desc", "test",
        ])
        self.assertEqual(result.exit_code, 0)
        mock_service.generate_node.assert_called_once()
        mock_mgr.create_generated_node.assert_called_once()
        mock_registry.register_external_node.assert_called_once_with(mock_node_def)
        self.assertIn("AI 节点已创建", result.output)

    def test_node_generate_high_risk(self, mock_cm_cls, mock_ai_cls, mock_custom_cls, mock_reg):
        """安全审查不通过时应报错"""
        mock_cm = MagicMock()
        mock_cm.get_ai_settings.return_value = {
            "api_key": "sk-test", "model": "gpt-4",
        }
        mock_cm_cls.return_value = mock_cm

        mock_service = MagicMock()
        mock_service.generate_node.return_value = self._make_high_risk_result()
        mock_ai_cls.return_value = mock_service

        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_mgr = MagicMock()
        mock_custom_cls.return_value = mock_mgr

        result = self.runner.invoke(app, [
            "node", "generate", "MyNode", "--desc", "test",
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("安全审查未通过", result.output)
        mock_mgr.create_generated_node.assert_not_called()

    def test_node_generate_node_creation_failure(self, mock_cm_cls, mock_ai_cls, mock_custom_cls, mock_reg):
        """create_generated_node 返回 None 时应报错"""
        mock_cm = MagicMock()
        mock_cm.get_ai_settings.return_value = {
            "api_key": "sk-test", "model": "gpt-4",
        }
        mock_cm_cls.return_value = mock_cm

        mock_service = MagicMock()
        mock_service.generate_node.return_value = self._make_safe_result()
        mock_ai_cls.return_value = mock_service

        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_mgr = MagicMock()
        mock_mgr.create_generated_node.return_value = None
        mock_custom_cls.return_value = mock_mgr

        result = self.runner.invoke(app, [
            "node", "generate", "MyNode", "--desc", "test",
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("创建失败", result.output)

    def test_node_generate_ai_exception(self, mock_cm_cls, mock_ai_cls, mock_custom_cls, mock_reg):
        """AI 服务异常时应报错"""
        mock_cm = MagicMock()
        mock_cm.get_ai_settings.return_value = {
            "api_key": "sk-test", "model": "gpt-4",
        }
        mock_cm_cls.return_value = mock_cm

        from src.core.ai_node_generator import AINodeGenerationError
        mock_service = MagicMock()
        mock_service.generate_node.side_effect = AINodeGenerationError(ErrorCode.AI_GENERATION_FAILED, "API timeout")
        mock_ai_cls.return_value = mock_service

        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_mgr = MagicMock()
        mock_custom_cls.return_value = mock_mgr

        result = self.runner.invoke(app, [
            "node", "generate", "MyNode", "--desc", "test",
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("API timeout", result.output)


# ===================================================================
# 11. node check-safety
# ===================================================================
# review_code_safety 在命令函数体内懒加载:
#   from src.core.code_safety import review_code_safety
# → 在定义模块 src.core.code_safety 处打补丁

@patch("src.core.code_safety.review_code_safety")
class TestCLINodeCheckSafetyCommand(unittest.TestCase):
    """node check-safety 命令"""

    def setUp(self):
        self.runner = CliRunner()

    def test_node_check_safety_safe(self, mock_review):
        """安全代码应显示低风险"""
        mock_result = SafetyReviewResult(
            risk_level="low",
            high_risks=[],
            medium_risks=[],
            low_risks=[],
        )
        mock_review.return_value = mock_result

        with tempfile.TemporaryDirectory() as _tmpdir:
            old_cwd = os.getcwd()
            os.chdir(_tmpdir)
            try:
                Path("safe_script.py").write_text("print('hello world')")
                result = self.runner.invoke(app, [
                    "node", "check-safety", "safe_script.py",
                ])
            finally:
                os.chdir(old_cwd)
        self.assertEqual(result.exit_code, 0)
        self.assertTrue("低风险" in result.output or "未检测到" in result.output)

    def test_node_check_safety_unsafe(self, mock_review):
        """含高风险代码应显示高风险"""
        mock_result = SafetyReviewResult(
            risk_level="high",
            high_risks=["调用了 os.system（执行系统命令）"],
            medium_risks=[],
            low_risks=[],
        )
        mock_review.return_value = mock_result

        with tempfile.TemporaryDirectory() as _tmpdir:
            old_cwd = os.getcwd()
            os.chdir(_tmpdir)
            try:
                Path("unsafe_script.py").write_text("import os; os.system('rm -rf /')")
                result = self.runner.invoke(app, [
                    "node", "check-safety", "unsafe_script.py",
                ])
            finally:
                os.chdir(old_cwd)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("高风险", result.output)

    def test_node_check_safety_file_not_found(self, mock_review):
        """不存在的文件应报错"""
        result = self.runner.invoke(app, [
            "node", "check-safety", "/nonexistent/path.py",
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("不存在", result.output)

    def test_node_check_safety_medium_risk(self, mock_review):
        """中风险代码应显示中风险和警告列表"""
        mock_result = SafetyReviewResult(
            risk_level="medium",
            high_risks=[],
            medium_risks=["使用 open() 写模式打开文件"],
            low_risks=[],
        )
        mock_review.return_value = mock_result

        with tempfile.TemporaryDirectory() as _tmpdir:
            old_cwd = os.getcwd()
            os.chdir(_tmpdir)
            try:
                Path("medium_script.py").write_text("open('/tmp/x', 'w')")
                result = self.runner.invoke(app, [
                    "node", "check-safety", "medium_script.py",
                ])
            finally:
                os.chdir(old_cwd)
        self.assertEqual(result.exit_code, 0)
        self.assertIn("中风险", result.output)

    def test_node_check_safety_read_error(self, mock_review):
        """读取文件失败时应报错"""
        result = self.runner.invoke(app, [
            "node", "check-safety", "/",
        ])
        self.assertNotEqual(result.exit_code, 0)


# ===================================================================
# 12. node repo list
# ===================================================================
# NodeRepoManager 在 _get_repo_mgr() 中懒加载:
#   from src.core.node_repo_manager import NodeRepoManager
# → 在定义模块 src.core.node_repo_manager 处打补丁

@patch("src.cli.get_registry")
@patch("src.cli.ConfigManager")
@patch("src.core.node_repo_manager.NodeRepoManager")
class TestCLINodeRepoListCommand(unittest.TestCase):
    """node repo list 命令"""

    def setUp(self):
        self.runner = CliRunner()

    def _make_remote_node(self, node_type, version="1.0"):
        node = MagicMock()
        node.latest_version.return_value = version
        return node

    def test_node_repo_list_success(self, mock_repo_cls, mock_cm_cls, mock_reg):
        """成功列出远程节点应显示表格"""
        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_cm = MagicMock()
        mock_cm.get_github_token.return_value = ""
        mock_cm_cls.return_value = mock_cm

        mock_mgr = MagicMock()
        mock_mgr._parse_github_url.return_value = ("owner", "repo")
        mock_manifest = MagicMock()
        mock_manifest.repo_name = "official-nodes"
        mock_manifest.repo_version = "1.0"
        mock_manifest.nodes = {
            "http_request": self._make_remote_node("http_request", "2.0"),
            "file_reader": self._make_remote_node("file_reader", "1.5"),
        }
        mock_mgr._fetch_remote_manifest.return_value = mock_manifest
        mock_mgr._version_mgr.scan_all_nodes.return_value = {}
        mock_repo_cls.return_value = mock_mgr

        result = self.runner.invoke(app, ["node", "repo", "list"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("http_request", result.output)
        self.assertIn("file_reader", result.output)

    def test_node_repo_list_fetch_fail(self, mock_repo_cls, mock_cm_cls, mock_reg):
        """获取远程清单失败时应报错"""
        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_cm = MagicMock()
        mock_cm.get_github_token.return_value = ""
        mock_cm_cls.return_value = mock_cm

        mock_mgr = MagicMock()
        mock_mgr._parse_github_url.return_value = ("owner", "repo")
        mock_mgr._fetch_remote_manifest.return_value = None
        mock_repo_cls.return_value = mock_mgr

        result = self.runner.invoke(app, ["node", "repo", "list"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("无法获取", result.output)

    def test_node_repo_list_url_parse_fail(self, mock_repo_cls, mock_cm_cls, mock_reg):
        """解析仓库 URL 失败时应报错"""
        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_cm = MagicMock()
        mock_cm.get_github_token.return_value = ""
        mock_cm_cls.return_value = mock_cm

        mock_mgr = MagicMock()
        mock_mgr._parse_github_url.return_value = None
        mock_repo_cls.return_value = mock_mgr

        result = self.runner.invoke(app, ["node", "repo", "list"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("无法解析", result.output)


# ===================================================================
# 13. node repo check-updates
# ===================================================================

@patch("src.cli.get_registry")
@patch("src.cli.ConfigManager")
@patch("src.core.node_repo_manager.NodeRepoManager")
class TestCLINodeRepoCheckUpdatesCommand(unittest.TestCase):
    """node repo check-updates 命令"""

    def setUp(self):
        self.runner = CliRunner()

    def test_node_repo_check_updates_no_updates(self, mock_repo_cls, mock_cm_cls, mock_reg):
        """无更新时应显示'所有节点已是最新'"""
        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_cm = MagicMock()
        mock_cm.get_github_token.return_value = ""
        mock_cm_cls.return_value = mock_cm

        mock_mgr = MagicMock()
        mock_result = MagicMock()
        mock_result.has_updates = False
        mock_result.new_nodes = []
        mock_result.updates = []
        mock_result.error = ""
        mock_result.repo_version = "1.0"
        mock_result.remote_repo_version = "1.0"
        mock_mgr.check_for_updates.return_value = mock_result
        mock_repo_cls.return_value = mock_mgr

        result = self.runner.invoke(app, ["node", "repo", "check-updates"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("所有节点已是最新", result.output)

    def test_node_repo_check_updates_has_updates(self, mock_repo_cls, mock_cm_cls, mock_reg):
        """有更新时应显示新版本"""
        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_cm = MagicMock()
        mock_cm.get_github_token.return_value = ""
        mock_cm_cls.return_value = mock_cm

        mock_mgr = MagicMock()
        update_item = MagicMock()
        update_item.node_type = "http_request"
        update_item.local_versions = ["1.0"]
        update_item.new_versions = ["2.0"]
        update_item.remote_versions = ["1.0", "2.0"]

        mock_result = MagicMock()
        mock_result.has_updates = True
        mock_result.new_nodes = ["new_node_a"]
        mock_result.updates = [update_item]
        mock_result.error = ""
        mock_result.repo_version = "1.0"
        mock_result.remote_repo_version = "2.0"
        mock_mgr.check_for_updates.return_value = mock_result
        mock_repo_cls.return_value = mock_mgr

        result = self.runner.invoke(app, ["node", "repo", "check-updates"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("http_request", result.output)
        self.assertIn("2.0", result.output)

    def test_node_repo_check_updates_error(self, mock_repo_cls, mock_cm_cls, mock_reg):
        """检查更新出现错误时应显示错误"""
        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_cm = MagicMock()
        mock_cm.get_github_token.return_value = ""
        mock_cm_cls.return_value = mock_cm

        mock_mgr = MagicMock()
        mock_result = MagicMock()
        mock_result.error = "网络连接失败"
        mock_mgr.check_for_updates.return_value = mock_result
        mock_repo_cls.return_value = mock_mgr

        result = self.runner.invoke(app, ["node", "repo", "check-updates"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("网络连接失败", result.output)


# ===================================================================
# 14. node repo install
# ===================================================================

@patch("src.cli.get_registry")
@patch("src.cli.ConfigManager")
@patch("src.core.node_repo_manager.NodeRepoManager")
class TestCLINodeRepoInstallCommand(unittest.TestCase):
    """node repo install 命令"""

    def setUp(self):
        self.runner = CliRunner()

    def test_node_repo_install_success(self, mock_repo_cls, mock_cm_cls, mock_reg):
        """安装成功时应显示成功消息并重新加载外部节点"""
        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_cm = MagicMock()
        mock_cm.get_github_token.return_value = ""
        mock_cm_cls.return_value = mock_cm

        mock_mgr = MagicMock()
        mock_mgr.list_remote_versions.return_value = ["1.0", "2.0"]
        mock_mgr.install_node_version.return_value = (True, "安装成功")
        mock_repo_cls.return_value = mock_mgr

        result = self.runner.invoke(app, [
            "node", "repo", "install", "http_request",
        ])
        self.assertEqual(result.exit_code, 0)
        mock_mgr.install_node_version.assert_called_once()
        mock_registry._load_external_nodes.assert_called_once()
        self.assertIn("✓", result.output)

    def test_node_repo_install_not_found(self, mock_repo_cls, mock_cm_cls, mock_reg):
        """远程仓库中未找到节点时应报错"""
        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_cm = MagicMock()
        mock_cm.get_github_token.return_value = ""
        mock_cm_cls.return_value = mock_cm

        mock_mgr = MagicMock()
        mock_mgr.list_remote_versions.return_value = []
        mock_repo_cls.return_value = mock_mgr

        result = self.runner.invoke(app, [
            "node", "repo", "install", "nonexistent_node",
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("未找到", result.output)

    def test_node_repo_install_version_not_found(self, mock_repo_cls, mock_cm_cls, mock_reg):
        """指定的版本不可用时应报错"""
        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_cm = MagicMock()
        mock_cm.get_github_token.return_value = ""
        mock_cm_cls.return_value = mock_cm

        mock_mgr = MagicMock()
        mock_mgr.list_remote_versions.return_value = ["1.0", "2.0"]
        mock_repo_cls.return_value = mock_mgr

        result = self.runner.invoke(app, [
            "node", "repo", "install", "http_request", "--version", "3.0",
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("版本", result.output)
        self.assertIn("不可用", result.output)

    def test_node_repo_install_failure(self, mock_repo_cls, mock_cm_cls, mock_reg):
        """安装失败时应显示错误消息"""
        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_cm = MagicMock()
        mock_cm.get_github_token.return_value = ""
        mock_cm_cls.return_value = mock_cm

        mock_mgr = MagicMock()
        mock_mgr.list_remote_versions.return_value = ["1.0", "2.0"]
        mock_mgr.install_node_version.return_value = (False, "下载失败")
        mock_repo_cls.return_value = mock_mgr

        result = self.runner.invoke(app, [
            "node", "repo", "install", "http_request",
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("下载失败", result.output)

    def test_node_repo_install_specific_version(self, mock_repo_cls, mock_cm_cls, mock_reg):
        """指定版本时应安装对应版本"""
        mock_registry = MagicMock()
        mock_registry._user_data_dir = "/tmp/user_data"
        mock_reg.return_value = mock_registry

        mock_cm = MagicMock()
        mock_cm.get_github_token.return_value = ""
        mock_cm_cls.return_value = mock_cm

        mock_mgr = MagicMock()
        mock_mgr.list_remote_versions.return_value = ["1.0", "2.0"]
        mock_mgr.install_node_version.return_value = (True, "安装成功")
        mock_repo_cls.return_value = mock_mgr

        result = self.runner.invoke(app, [
            "node", "repo", "install", "http_request", "--version", "1.0",
        ])
        self.assertEqual(result.exit_code, 0)
        call_args = mock_mgr.install_node_version.call_args
        self.assertEqual(call_args[0][1], "1.0")


# ===================================================================
# 15. config github-login
# ===================================================================
# GitHubOAuth 在命令函数体内懒加载:
#   from src.core.github_oauth import GitHubOAuth
# → 在定义模块 src.core.github_oauth 处打补丁

@patch("src.cli.ConfigManager")
@patch("src.core.github_oauth.GitHubOAuth")
class TestCLIConfigGitHubLoginCommand(unittest.TestCase):
    """config github-login 命令"""

    def setUp(self):
        self.runner = CliRunner()

    def test_config_github_login_success(self, mock_oauth_cls, mock_cm_cls):
        """登录成功时应保存 token 和用户名"""
        mock_oauth = MagicMock()
        mock_oauth.authorize.return_value = (True, "gh_token_abc", "testuser")
        mock_oauth_cls.return_value = mock_oauth

        mock_cm = MagicMock()
        mock_cm_cls.return_value = mock_cm

        result = self.runner.invoke(app, ["config", "github-login"])
        self.assertEqual(result.exit_code, 0)
        mock_cm.set_github_settings.assert_called_once_with({
            "token": "gh_token_abc",
            "username": "testuser",
            "connected": True,
        })
        self.assertIn("授权成功", result.output)
        self.assertIn("testuser", result.output)

    def test_config_github_login_failure(self, mock_oauth_cls, mock_cm_cls):
        """授权失败时应报错"""
        mock_oauth = MagicMock()
        mock_oauth.authorize.return_value = (False, "", "user cancelled")
        mock_oauth_cls.return_value = mock_oauth

        mock_cm = MagicMock()
        mock_cm_cls.return_value = mock_cm

        result = self.runner.invoke(app, ["config", "github-login"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("授权失败", result.output)

    def test_config_github_login_with_timeout(self, mock_oauth_cls, mock_cm_cls):
        """应支持 --timeout 参数"""
        mock_oauth = MagicMock()
        mock_oauth.authorize.return_value = (True, "token", "user")
        mock_oauth_cls.return_value = mock_oauth

        mock_cm = MagicMock()
        mock_cm_cls.return_value = mock_cm

        result = self.runner.invoke(app, [
            "config", "github-login", "--timeout", "120",
        ])
        self.assertEqual(result.exit_code, 0)
        call_kwargs = mock_oauth.authorize.call_args[1]
        self.assertEqual(call_kwargs.get("timeout"), 120)


# ===================================================================
# 16. config github-logout
# ===================================================================

@patch("src.cli.ConfigManager")
class TestCLIConfigGitHubLogoutCommand(unittest.TestCase):
    """config github-logout 命令"""

    def setUp(self):
        self.runner = CliRunner()

    def test_config_github_logout(self, mock_cm_cls):
        """登出时应清除 token"""
        mock_cm = MagicMock()
        mock_cm_cls.return_value = mock_cm

        result = self.runner.invoke(app, ["config", "github-logout"])
        self.assertEqual(result.exit_code, 0)
        mock_cm.set_github_settings.assert_called_once_with({
            "token": "",
            "username": "",
            "connected": False,
        })
        self.assertIn("已断开", result.output)


# ===================================================================
# 17. config set — 敏感键处理
# ===================================================================

@patch("src.cli.ConfigManager")
class TestCLIConfigSetSensitiveCommand(unittest.TestCase):
    """config set — 敏感字段加密存储"""

    def setUp(self):
        self.runner = CliRunner()

    def test_config_set_ai_settings_api_key(self, mock_cm_cls):
        """设置 ai_settings 时应调用 set_ai_settings 并脱敏显示 api_key"""
        mock_cm = MagicMock()
        mock_cm.config = {}
        mock_cm_cls.return_value = mock_cm

        result = self.runner.invoke(app, [
            "config", "set", "ai_settings",
            '{"api_key":"sk-test","model":"gpt-4"}',
        ])
        self.assertEqual(result.exit_code, 0)
        mock_cm.set_ai_settings.assert_called_once()
        args, _ = mock_cm.set_ai_settings.call_args
        self.assertEqual(args[0]["api_key"], "sk-test")
        # 验证输出中 api_key 被脱敏
        self.assertIn("******", result.output)
        self.assertNotIn("sk-test", result.output)

    def test_config_set_ai_settings_dot_path(self, mock_cm_cls):
        """使用点号路径 ai_settings.api_key 应调用 set_ai_settings"""
        mock_cm = MagicMock()
        mock_cm.config = {}
        mock_cm.get_ai_settings.return_value = {
            "api_key": "",
            "model": "gpt-3.5-turbo",
            "base_url": "",
            "temperature": 0.2,
        }
        mock_cm_cls.return_value = mock_cm

        result = self.runner.invoke(app, [
            "config", "set", "ai_settings.api_key", "sk-dotpath",
        ])
        self.assertEqual(result.exit_code, 0)
        mock_cm.set_ai_settings.assert_called_once()
        args, _ = mock_cm.set_ai_settings.call_args
        self.assertEqual(args[0].get("api_key"), "sk-dotpath")

    def test_config_set_non_sensitive_flat_key(self, mock_cm_cls):
        """普通非敏感键应正常赋值"""
        mock_cm = MagicMock()
        mock_cm.config = {}
        mock_cm_cls.return_value = mock_cm

        result = self.runner.invoke(app, [
            "config", "set", "theme", "dark",
        ])
        self.assertEqual(result.exit_code, 0)
        self.assertEqual(mock_cm.config["theme"], "dark")
        mock_cm.save_config_sync.assert_called_once()

    def test_config_set_github_settings(self, mock_cm_cls):
        """设置 github_settings 时应调用 set_github_settings"""
        mock_cm = MagicMock()
        mock_cm.config = {}
        mock_cm_cls.return_value = mock_cm

        result = self.runner.invoke(app, [
            "config", "set", "github_settings",
            '{"token":"ghp_test","username":"test"}',
        ])
        self.assertEqual(result.exit_code, 0)
        mock_cm.set_github_settings.assert_called_once()
        args, _ = mock_cm.set_github_settings.call_args
        self.assertEqual(args[0]["token"], "ghp_test")

    def test_config_set_sensitive_key_invalid_json(self, mock_cm_cls):
        """敏感键设置非 JSON 对象时应警告"""
        mock_cm = MagicMock()
        mock_cm.config = {}
        mock_cm_cls.return_value = mock_cm

        result = self.runner.invoke(app, [
            "config", "set", "ai_settings", "not-a-json",
        ])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("警告", result.output)


if __name__ == "__main__":
    unittest.main()


# ===================================================================
# TestCLIWorkflowEditCommands — 工作流编辑命令
# ===================================================================

class TestCLIWorkflowEditCommands(unittest.TestCase):
    """workflow create/delete/rename/add-node/remove-node/update-node/connect/disconnect"""

    def setUp(self):
        self.runner = CliRunner()

    # ── create ─────────────────────────────────────

    def test_workflow_create_success(self):
        """创建空工作流应成功"""
        with tempfile.TemporaryDirectory() as _tmpdir:
            old_cwd = os.getcwd()
            os.chdir(_tmpdir)
            try:
                result = self.runner.invoke(app, ["workflow", "create", "test_wf"])
                self.assertEqual(result.exit_code, 0)
                self.assertIn("已创建", result.output)
                self.assertTrue(Path("workflows/test_wf/workflow.json").exists())
            finally:
                os.chdir(old_cwd)

    def test_workflow_create_duplicate(self):
        """重复创建工作流应报错"""
        with tempfile.TemporaryDirectory() as _tmpdir:
            old_cwd = os.getcwd()
            os.chdir(_tmpdir)
            try:
                self.runner.invoke(app, ["workflow", "create", "dup_wf"])
                result = self.runner.invoke(app, ["workflow", "create", "dup_wf"])
                self.assertNotEqual(result.exit_code, 0)
                self.assertIn("已存在", result.output)
            finally:
                os.chdir(old_cwd)

    # ── delete ─────────────────────────────────────

    def test_workflow_delete_success(self):
        """删除工作流应成功"""
        with tempfile.TemporaryDirectory() as _tmpdir:
            old_cwd = os.getcwd()
            os.chdir(_tmpdir)
            try:
                self.runner.invoke(app, ["workflow", "create", "del_wf"])
                wf_path = "workflows/del_wf/workflow.json"
                self.assertTrue(Path(wf_path).exists())

                result = self.runner.invoke(app, ["workflow", "delete", wf_path])
                self.assertEqual(result.exit_code, 0)
                self.assertIn("已删除", result.output)
                self.assertFalse(Path("workflows/del_wf").exists())
            finally:
                os.chdir(old_cwd)

    def test_workflow_delete_nonexistent(self):
        """删除不存在的工作流应报错"""
        result = self.runner.invoke(app, ["workflow", "delete", "/nonexistent/wf.json"])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("不存在", result.output)

    # ── rename ─────────────────────────────────────

    def test_workflow_rename_success(self):
        """重命名工作流应成功"""
        with tempfile.TemporaryDirectory() as _tmpdir:
            old_cwd = os.getcwd()
            os.chdir(_tmpdir)
            try:
                self.runner.invoke(app, ["workflow", "create", "old_name"])
                old_path = "workflows/old_name/workflow.json"
                self.assertTrue(Path(old_path).exists())

                result = self.runner.invoke(app, ["workflow", "rename", old_path, "new_name"])
                self.assertEqual(result.exit_code, 0)
                self.assertIn("已重命名", result.output)
                self.assertFalse(Path("workflows/old_name").exists())
                self.assertTrue(Path("workflows/new_name/workflow.json").exists())
            finally:
                os.chdir(old_cwd)

    def test_workflow_rename_target_exists(self):
        """重命名到已存在的名称应报错"""
        with tempfile.TemporaryDirectory() as _tmpdir:
            old_cwd = os.getcwd()
            os.chdir(_tmpdir)
            try:
                self.runner.invoke(app, ["workflow", "create", "src"])
                self.runner.invoke(app, ["workflow", "create", "dst"])
                result = self.runner.invoke(app, ["workflow", "rename",
                                                   "workflows/src/workflow.json", "dst"])
                self.assertNotEqual(result.exit_code, 0)
                self.assertIn("已存在", result.output)
            finally:
                os.chdir(old_cwd)

    # ── add-node ───────────────────────────────────

    @patch("src.cli._load_workflow")
    @patch("src.cli._extract_node_positions")
    def test_workflow_add_node_defaults(self, mock_pos, mock_load):
        """add-node 应生成节点 ID 并使用默认配置"""
        mock_executor = MagicMock()
        mock_executor.nodes = {}
        mock_executor.workflow_name = "test_wf"
        mock_load.return_value = mock_executor
        mock_pos.return_value = {}

        result = self.runner.invoke(app, [
            "workflow", "add-node", "/fake/wf.json", "variable_assign",
        ])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("node1", result.output)
        self.assertIn("variable_assign", result.output)
        # 应调用 add_node
        mock_executor.add_node.assert_called_once()
        # 应调用 save_workflow
        mock_executor.save_workflow.assert_called_once()

    @patch("src.cli._load_workflow")
    @patch("src.cli._extract_node_positions")
    def test_workflow_add_node_with_config(self, mock_pos, mock_load):
        """add-node 应传递 --config 参数"""
        mock_executor = MagicMock()
        mock_executor.nodes = {}
        mock_executor.workflow_name = "test_wf"
        mock_load.return_value = mock_executor
        mock_pos.return_value = {}

        result = self.runner.invoke(app, [
            "workflow", "add-node", "/fake/wf.json", "variable_assign",
            "--config", "variable_name=x",
            "--config", "value=42",
        ])
        self.assertEqual(result.exit_code, 0)
        # 验证传递给 add_node 的 node 包含正确的 config
        call_args = mock_executor.add_node.call_args
        added_node = call_args[0][0]
        self.assertEqual(added_node.config.get("variable_name"), "x")
        self.assertEqual(added_node.config.get("value"), "42")

    @patch("src.cli._load_workflow")
    def test_workflow_add_node_generates_unique_id(self, mock_load):
        """add-node 应生成不重复的 ID"""
        mock_executor = MagicMock()
        mock_executor.nodes = {"node1": MagicMock()}
        mock_executor.workflow_name = "test_wf"
        mock_load.return_value = mock_executor

        with patch("src.cli._extract_node_positions", return_value={}):
            result = self.runner.invoke(app, [
                "workflow", "add-node", "/fake/wf.json", "variable_assign",
            ])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("node2", result.output)

    # ── remove-node ────────────────────────────────

    @patch("src.cli._load_workflow")
    @patch("src.cli._extract_node_positions")
    def test_workflow_remove_node_success(self, mock_pos, mock_load):
        """remove-node 应删除节点并清理关联"""
        mock_node = MagicMock()
        mock_node.node_id = "n1"
        mock_executor = MagicMock()
        mock_executor.nodes = {"n1": mock_node, "n2": MagicMock()}
        mock_executor.edges = []
        mock_executor.workflow_name = "test_wf"
        mock_load.return_value = mock_executor
        mock_pos.return_value = {}

        result = self.runner.invoke(app, [
            "workflow", "remove-node", "/fake/wf.json", "n1",
        ])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("已删除", result.output)
        # verify node was removed from dict
        self.assertNotIn("n1", mock_executor.nodes)

    @patch("src.cli._load_workflow")
    def test_workflow_remove_node_nonexistent(self, mock_load):
        """remove-node 对不存在的节点应报错"""
        mock_executor = MagicMock()
        mock_executor.nodes = {"n1": MagicMock()}
        mock_load.return_value = mock_executor

        result = self.runner.invoke(app, [
            "workflow", "remove-node", "/fake/wf.json", "ghost",
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("不存在", result.output)

    # ── update-node ────────────────────────────────

    @patch("src.cli._load_workflow")
    @patch("src.cli._extract_node_positions")
    def test_workflow_update_node_success(self, mock_pos, mock_load):
        """update-node 应更新节点配置"""
        mock_node = MagicMock()
        mock_node.config = {}
        mock_executor = MagicMock()
        mock_executor.nodes = {"n1": mock_node}
        mock_executor.workflow_name = "test_wf"
        mock_load.return_value = mock_executor
        mock_pos.return_value = {}

        result = self.runner.invoke(app, [
            "workflow", "update-node", "/fake/wf.json", "n1",
            "key1=val1", "key2=val2",
        ])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("已更新", result.output)
        self.assertEqual(mock_node.config.get("key1"), "val1")
        self.assertEqual(mock_node.config.get("key2"), "val2")

    @patch("src.cli._load_workflow")
    def test_workflow_update_node_no_config(self, mock_load):
        """update-node 无配置项时应报错"""
        mock_executor = MagicMock()
        mock_executor.nodes = {"n1": MagicMock()}
        mock_load.return_value = mock_executor

        # 不传 config 参数（空列表）
        result = self.runner.invoke(app, [
            "workflow", "update-node", "/fake/wf.json", "n1",
        ])
        self.assertNotEqual(result.exit_code, 0)

    # ── connect ────────────────────────────────────

    @patch("src.cli._load_workflow")
    @patch("src.cli._extract_node_positions")
    def test_workflow_connect_success(self, mock_pos, mock_load):
        """connect 应连接两个节点"""
        mock_from = MagicMock()
        mock_to = MagicMock()
        mock_executor = MagicMock()
        mock_executor.nodes = {"from_node": mock_from, "to_node": mock_to}
        mock_executor.edges = []
        mock_executor.workflow_name = "test_wf"
        mock_load.return_value = mock_executor
        mock_pos.return_value = {}

        result = self.runner.invoke(app, [
            "workflow", "connect", "/fake/wf.json", "from_node", "to_node",
        ])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("已连接", result.output)
        mock_executor.add_edge.assert_called_once_with(
            "from_node", "output", "to_node", "input"
        )

    @patch("src.cli._load_workflow")
    def test_workflow_connect_nonexistent_node(self, mock_load):
        """connect 连接不存在的节点应报错"""
        mock_executor = MagicMock()
        mock_executor.nodes = {"a": MagicMock()}
        mock_load.return_value = mock_executor

        result = self.runner.invoke(app, [
            "workflow", "connect", "/fake/wf.json", "a", "ghost",
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("不存在", result.output)

    @patch("src.cli._load_workflow")
    def test_workflow_connect_duplicate(self, mock_load):
        """connect 重复连接应报错"""
        from collections import namedtuple
        Edge = namedtuple("Edge", ["from_node", "from_port", "to_node", "to_port"])
        mock_executor = MagicMock()
        mock_executor.nodes = {"a": MagicMock(), "b": MagicMock()}
        mock_executor.edges = [Edge("a", "output", "b", "input")]
        mock_load.return_value = mock_executor

        result = self.runner.invoke(app, [
            "workflow", "connect", "/fake/wf.json", "a", "b",
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("已存在", result.output)

    # ── disconnect ─────────────────────────────────

    @patch("src.cli._load_workflow")
    @patch("src.cli._extract_node_positions")
    def test_workflow_disconnect_success(self, mock_pos, mock_load):
        """disconnect 应断开连接"""
        from collections import namedtuple
        Edge = namedtuple("Edge", ["from_node", "from_port", "to_node", "to_port"])
        mock_from = MagicMock()
        mock_from.outputs = ["to_node"]
        mock_to = MagicMock()
        mock_to.inputs = ["from_node"]
        mock_executor = MagicMock()
        mock_executor.nodes = {"from_node": mock_from, "to_node": mock_to}
        mock_executor.edges = [Edge("from_node", "output", "to_node", "input")]
        mock_load.return_value = mock_executor
        mock_pos.return_value = {}

        result = self.runner.invoke(app, [
            "workflow", "disconnect", "/fake/wf.json", "from_node", "to_node",
        ])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("已断开", result.output)
        self.assertEqual(len(mock_executor.edges), 0)

    @patch("src.cli._load_workflow")
    def test_workflow_disconnect_nonexistent(self, mock_load):
        """disconnect 断开不存在的连接应报错"""
        mock_executor = MagicMock()
        mock_executor.nodes = {"a": MagicMock(), "b": MagicMock()}
        mock_executor.edges = []
        mock_load.return_value = mock_executor

        result = self.runner.invoke(app, [
            "workflow", "disconnect", "/fake/wf.json", "a", "b",
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("未找到", result.output)
