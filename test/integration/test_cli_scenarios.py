"""
CLI 场景测试 — 真实端到端工作流
"""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch
import tempfile

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from typer.testing import CliRunner
from src.cli import app


class TestCLIRunScenario(unittest.TestCase):
    """run 命令端到端场景"""

    def setUp(self):
        self.runner = CliRunner()

    @patch("src.cli._load_workflow")
    def test_run_workflow_success_full_output(self, mock_load):
        """场景：成功执行工作流，查看完整输出"""
        mock_executor = MagicMock()
        mock_executor.workflow_name = "测试工作流"
        mock_executor.nodes = [MagicMock(), MagicMock(), MagicMock()]
        mock_executor.prepare_environment.return_value = True
        mock_executor.execute.return_value = {
            "success": True,
            "run_id": "run-001",
            "duration_ms": 1500,
            "workflow_name": "测试工作流",
            "nodes": [],
        }
        mock_load.return_value = mock_executor

        with patch("src.cli.Path.exists", return_value=True), \
             patch("src.cli.Path.is_file", return_value=True):
            result = self.runner.invoke(app, ["run", "/fake/wf.json"])
            self.assertEqual(result.exit_code, 0)
            self.assertIn("测试工作流", result.output)
            self.assertIn("1500", result.output)
            self.assertIn("3", result.output)
            self.assertIn("执行成功", result.output)

    @patch("src.cli._load_workflow")
    def test_run_workflow_partial_failure(self, mock_load):
        """场景：工作流部分节点失败"""
        mock_executor = MagicMock()
        mock_executor.workflow_name = "partial_fail_wf"
        mock_executor.nodes = [MagicMock(), MagicMock()]
        mock_executor.prepare_environment.return_value = True
        mock_executor.execute.return_value = {
            "success": False,
            "run_id": "run-002",
            "duration_ms": 800,
            "error": "Node 'step2' failed: connection refused",
        }
        mock_load.return_value = mock_executor

        with patch("src.cli.Path.exists", return_value=True), \
             patch("src.cli.Path.is_file", return_value=True):
            result = self.runner.invoke(app, ["run", "/fake/wf.json"])
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("执行失败", result.output)
            self.assertIn("connection refused", result.output)

    @patch("src.cli._load_workflow")
    def test_run_with_json_flag_then_parse(self, mock_load):
        """场景：使用 --json 标志，管道式处理结果"""
        mock_executor = MagicMock()
        mock_executor.workflow_name = "json_pipeline"
        mock_executor.nodes = [MagicMock()]
        mock_executor.prepare_environment.return_value = True
        mock_executor.execute.return_value = {
            "success": True,
            "duration_ms": 200,
            "workflow_name": "json_pipeline",
            "final_context": {"result": 42},
        }
        mock_load.return_value = mock_executor

        with patch("src.cli.Path.exists", return_value=True), \
             patch("src.cli.Path.is_file", return_value=True):
            result = self.runner.invoke(app, ["run", "/fake/wf.json", "--json"])
            self.assertEqual(result.exit_code, 0)
            # 提取 JSON output (可能被 Rich 输出包围)
            output = result.output.strip()
            # 找到 JSON 部分 — 尝试解析完整文本或逐行
            data = None
            try:
                data = json.loads(output)
            except json.JSONDecodeError:
                lines = output.splitlines()
                for line in lines:
                    try:
                        data = json.loads(line)
                        break
                    except json.JSONDecodeError:
                        continue
            self.assertIsNotNone(data, f"No JSON found in: {output}")
            self.assertTrue(data["success"])
            self.assertEqual(data["workflow"], "json_pipeline")
            # completed_nodes 由回调累计，mock 中无回调触发故为 0
            self.assertEqual(data["completed_nodes"], 0)
            self.assertIn("logs", data)

    def test_run_nonexistent_workflow(self):
        """场景：运行不存在的文件"""
        with patch("src.cli.Path.exists", return_value=False):
            result = self.runner.invoke(app, ["run", "/nonexistent/workflow.json"])
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("不存在", result.output)

    @patch("src.cli._load_workflow")
    def test_run_then_verify_callbacks(self, mock_load):
        """场景：验证所有 4 个回调被传递"""
        mock_executor = MagicMock()
        mock_executor.workflow_name = "cb_test"
        mock_executor.nodes = [MagicMock(), MagicMock()]
        mock_executor.prepare_environment.return_value = True
        mock_executor.execute.return_value = {"success": True}
        mock_load.return_value = mock_executor

        with patch("src.cli.Path.exists", return_value=True), \
             patch("src.cli.Path.is_file", return_value=True):
            self.runner.invoke(app, ["run", "/fake/wf.json", "--verbose"])
            _, kwargs = mock_executor.execute.call_args
            self.assertIn("on_node_start", kwargs)
            self.assertIn("on_node_complete", kwargs)
            self.assertIn("on_node_progress", kwargs)
            self.assertIn("on_node_log", kwargs)
            self.assertTrue(callable(kwargs["on_node_start"]))
            self.assertTrue(callable(kwargs["on_node_complete"]))
            self.assertTrue(callable(kwargs["on_node_progress"]))
            self.assertTrue(callable(kwargs["on_node_log"]))


class TestCLIConfigScenario(unittest.TestCase):
    """config 命令端到端场景"""

    def setUp(self):
        self.runner = CliRunner()

    @patch("src.cli.ConfigManager")
    def test_config_set_then_show_flow(self, mock_mgr_cls):
        """场景：设置配置项，然后查看配置列表"""
        mock_mgr = MagicMock()
        mock_mgr.config = {"theme": "dark", "lang": "zh-CN"}
        mock_mgr.get_execution_stats.return_value = {
            "total_runs": 0, "successful_runs": 0, "failed_runs": 0, "success_rate": 0.0
        }
        mock_mgr_cls.return_value = mock_mgr

        result = self.runner.invoke(app, ["config", "show"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("theme", result.output)
        self.assertIn("dark", result.output)
        self.assertIn("lang", result.output)
        self.assertIn("zh-CN", result.output)

    @patch("src.cli.ConfigManager")
    def test_config_set_ai_settings_redacted_display(self, mock_mgr_cls):
        """场景：设置 AI 配置，api_key 显示为 ******"""
        mock_mgr = MagicMock()
        # config 中包含 ai_settings 键以使循环进入对应分支
        mock_mgr.config = {"ai_settings": "encrypted_placeholder"}
        mock_mgr.get_ai_settings.return_value = {
            "api_key": "sk-real-key",
            "model": "gpt-4",
            "base_url": "https://api.openai.com/v1",
        }
        mock_mgr.get_execution_stats.return_value = {
            "total_runs": 0, "successful_runs": 0, "failed_runs": 0, "success_rate": 0.0
        }
        mock_mgr_cls.return_value = mock_mgr

        result = self.runner.invoke(app, ["config", "show"])
        self.assertEqual(result.exit_code, 0)
        # api_key 应被脱敏
        self.assertNotIn("sk-real-key", result.output)
        # model 和 base_url 应正常显示
        self.assertIn("gpt-4", result.output)
        self.assertIn("api.openai.com", result.output)

    @patch("src.cli.ConfigManager")
    @patch("src.cli._resolve_config_value")
    def test_config_set_dot_path_sensitive(self, mock_resolve, mock_mgr_cls):
        """场景：通过点路径设置敏感字段"""
        mock_resolve.return_value = True  # 表示已通过 setter 处理
        mock_mgr = MagicMock()
        mock_mgr.config = {}
        mock_mgr_cls.return_value = mock_mgr

        result = self.runner.invoke(
            app, ["config", "set", "ai_settings.api_key", "sk-dotpath"]
        )
        self.assertEqual(result.exit_code, 0)
        self.assertIn("******", result.output)
        mock_resolve.assert_called_once()


class TestCLIScheduleScenario(unittest.TestCase):
    """schedule 命令端到端场景"""

    def setUp(self):
        self.runner = CliRunner()

    @patch("src.cli.HeadlessScheduler")
    def test_schedule_full_lifecycle(self, mock_sched_cls):
        """场景：添加任务 → 查看列表 → 更新 → 查看 → 删除"""
        mock_sched = MagicMock()
        mock_sched_cls.return_value = mock_sched

        # 1. add
        mock_sched.add_task.return_value = "task-001"
        with patch("src.cli.Path.exists", return_value=True):
            r1 = self.runner.invoke(app, ["schedule", "add", "/fake/wf.json", "-c", "0 * * * *", "-n", "nightly"])
            self.assertEqual(r1.exit_code, 0)
            self.assertIn("task-001", r1.output)

        # 2. list
        mock_sched.list_tasks.return_value = [{"id": "task-001", "workflow_name": "nightly", "cron_expression": "0 * * * *", "enabled": True, "last_run": None, "next_run": "2026-05-17 11:00:00"}]
        r2 = self.runner.invoke(app, ["schedule", "list"])
        self.assertEqual(r2.exit_code, 0)
        self.assertIn("task-001", r2.output)

        # 3. update
        mock_sched.get_task.return_value = {"id": "task-001", "workflow_name": "nightly"}
        mock_sched.update_task.return_value = True
        r3 = self.runner.invoke(app, ["schedule", "update", "task-001", "--cron", "0 */2 * * *"])
        self.assertEqual(r3.exit_code, 0)
        self.assertIn("已更新", r3.output)

        # 4. remove
        mock_sched.remove_task.return_value = True
        r4 = self.runner.invoke(app, ["schedule", "remove", "task-001"])
        self.assertEqual(r4.exit_code, 0)
        self.assertIn("已删除", r4.output)

    @patch("src.cli.HeadlessScheduler")
    def test_schedule_daemon_start_stop_signals(self, mock_sched_cls):
        """场景：启动守护进程 → 收到 SIGTERM → 停止"""
        mock_sched = MagicMock()
        mock_sched.is_running = True
        mock_sched_cls.return_value = mock_sched

        # Mock signal handler registration
        with patch("signal.signal") as mock_signal, \
             patch("time.sleep", side_effect=KeyboardInterrupt):
            result = self.runner.invoke(app, ["schedule", "daemon", "--tick", "5"])
            self.assertEqual(result.exit_code, 0)
            self.assertIn("调度器", result.output)


class TestCLINodeScenario(unittest.TestCase):
    """node 命令端到端场景"""

    def setUp(self):
        self.runner = CliRunner()

    @patch("src.cli.get_registry")
    @patch("src.core.custom_node_manager.CustomNodeManager")
    def test_node_create_then_delete_scenario(self, mock_mgr_cls, mock_reg_cls):
        """场景：创建节点 → 列表出现 → 删除 → 列表消失"""
        mock_registry = MagicMock()
        mock_reg_cls.return_value = mock_registry
        mock_registry._user_data_dir = "/tmp/test_user_data"

        mock_mgr = MagicMock()
        mock_mgr_cls.return_value = mock_mgr

        # create returns a NodeDefinition-like object
        node_def = MagicMock()
        node_def.name = "MyNode"
        node_def.node_type = "custom_mynode_123456"
        mock_mgr.create_node.return_value = node_def

        # 1. create
        r1 = self.runner.invoke(app, ["node", "create", "MyNode", "-d", "test node"])
        self.assertEqual(r1.exit_code, 0)
        self.assertIn("MyNode", r1.output)
        self.assertIn("custom_mynode_123456", r1.output)
        mock_mgr.create_node.assert_called_once_with("MyNode", "test node", "自定义")
        mock_registry.register_external_node.assert_called_once_with(node_def)

        # 2. list
        mock_registry.get_all_nodes.return_value = [{"name": "MyNode", "category": "自定义", "description": "test node", "version": "1.0"}]
        r2 = self.runner.invoke(app, ["node", "list"])
        self.assertEqual(r2.exit_code, 0)
        self.assertIn("MyNode", r2.output)

        # 3. delete
        mock_mgr.delete_node.return_value = True
        r3 = self.runner.invoke(app, ["node", "delete", "custom_mynode_123456"])
        self.assertEqual(r3.exit_code, 0)
        self.assertIn("已删除", r3.output)
        mock_mgr.delete_node.assert_called_once_with("custom_mynode_123456")
        mock_registry.unregister_node.assert_called_once_with("custom_mynode_123456")

    @patch("src.cli.get_registry")
    @patch("src.core.custom_node_manager.CustomNodeManager")
    def test_node_export_then_import_scenario(self, mock_mgr_cls, mock_reg_cls):
        """场景：导出节点 → 删除 → 导入 → 列表恢复"""
        mock_registry = MagicMock()
        mock_reg_cls.return_value = mock_registry
        mock_registry._user_data_dir = "/tmp/test_user_data"

        mock_mgr = MagicMock()
        mock_mgr_cls.return_value = mock_mgr

        # 1. export
        mock_mgr.export_node.return_value = True
        r1 = self.runner.invoke(app, ["node", "export", "custom_test", "/tmp/node.zip"])
        self.assertEqual(r1.exit_code, 0)
        self.assertIn("已导出", r1.output)
        mock_mgr.export_node.assert_called_once_with("custom_test", "/tmp/node.zip", all_versions=False)

        # 2. delete
        mock_mgr.delete_node.return_value = True
        r2 = self.runner.invoke(app, ["node", "delete", "custom_test"])
        self.assertEqual(r2.exit_code, 0)

        # 3. import
        mock_mgr.import_node.return_value = "custom_test"
        r3 = self.runner.invoke(app, ["node", "import", "/tmp/node.zip"])
        self.assertEqual(r3.exit_code, 0)
        self.assertIn("已导入", r3.output)
        mock_mgr.import_node.assert_called_once_with("/tmp/node.zip")

    @patch("src.cli.get_registry")
    @patch("src.core.custom_node_manager.CustomNodeManager")
    @patch("src.core.ai_node_generator.AINodeGenerationService")
    def test_node_ai_generate_scenario(self, mock_ai_cls, mock_mgr_cls, mock_reg_cls):
        """场景：AI 生成节点 → 列表出现"""
        from src.core.code_safety import SafetyReviewResult

        mock_registry = MagicMock()
        mock_reg_cls.return_value = mock_registry
        mock_registry._user_data_dir = "/tmp/test_user_data"

        mock_mgr = MagicMock()
        mock_mgr_cls.return_value = mock_mgr

        # Mock AI service
        mock_ai = MagicMock()
        mock_ai_cls.return_value = mock_ai

        from src.core.ai_node_generator import GeneratedNodeResult
        mock_ai.generate_node.return_value = GeneratedNodeResult(
            name="AI Node",
            description="AI generated",
            source_code="def execute(self, input_data): return {}",
            config_schema={"param": {"type": "string", "label": "Param"}},
            dependencies=[],
            safety_review=SafetyReviewResult(
                risk_level="low",
                high_risks=[],
                medium_risks=[],
                low_risks=[],
            ),
        )

        # Mock ConfigManager for AI settings
        with patch("src.cli.ConfigManager") as mock_cfg_cls:
            mock_cfg = MagicMock()
            mock_cfg.get_ai_settings.return_value = {
                "api_key": "sk-test",
                "model": "gpt-4",
                "base_url": "https://api.openai.com/v1",
            }
            mock_cfg_cls.return_value = mock_cfg

            # Mock create_generated_node
            node_def = MagicMock()
            node_def.name = "AI Node"
            node_def.node_type = "custom_ai_node_123456"
            mock_mgr.create_generated_node.return_value = node_def

            r = self.runner.invoke(app, ["node", "generate", "AI Node", "-d", "test"])
            self.assertEqual(r.exit_code, 0)
            self.assertIn("AI Node", r.output)
            mock_mgr.create_generated_node.assert_called_once()
            mock_registry.register_external_node.assert_called_once()


class TestCLIConfigGitHubScenario(unittest.TestCase):
    """config github-login/logout 场景"""

    def setUp(self):
        self.runner = CliRunner()

    @patch("src.cli.ConfigManager")
    @patch("src.core.github_oauth.GitHubOAuth")
    def test_github_login_then_logout_scenario(self, mock_oauth_cls, mock_cfg_cls):
        """场景：GitHub 登录 → 配置中有 token → 登出 → token 清除"""
        mock_cfg = MagicMock()
        mock_cfg_cls.return_value = mock_cfg

        mock_oauth = MagicMock()
        mock_oauth_cls.return_value = mock_oauth
        mock_oauth.authorize.return_value = (True, "gho_token123", "testuser")

        # 1. login (mock user_code callback is internal)
        r1 = self.runner.invoke(app, ["config", "github-login", "--timeout", "600"])
        self.assertEqual(r1.exit_code, 0)
        self.assertIn("testuser", r1.output)
        mock_oauth.authorize.assert_called_once()
        _, kwargs = mock_oauth.authorize.call_args
        self.assertEqual(kwargs["timeout"], 600)
        mock_cfg.set_github_settings.assert_called_once_with({
            "token": "gho_token123",
            "username": "testuser",
            "connected": True,
        })

        # 2. logout
        mock_cfg.reset_mock()
        r2 = self.runner.invoke(app, ["config", "github-logout"])
        self.assertEqual(r2.exit_code, 0)
        mock_cfg.set_github_settings.assert_called_once_with({
            "token": "",
            "username": "",
            "connected": False,
        })


class TestCLIWorkflowScenario(unittest.TestCase):
    """workflow 命令端到端场景"""

    def setUp(self):
        self.runner = CliRunner()

    @patch("src.cli._load_workflow")
    def test_workflow_validate_then_describe_scenario(self, mock_load):
        """场景：验证工作流 → 查看详情"""
        from collections import namedtuple
        Edge = namedtuple("Edge", ["from_node", "from_port", "to_node", "to_port"])

        mock_executor = MagicMock()
        mock_load.return_value = mock_executor

        # 1. validate
        mock_executor.workflow_name = "data_pipeline"
        mock_executor.nodes = {"n1": MagicMock(), "n2": MagicMock(), "n3": MagicMock()}
        mock_executor.edges = [MagicMock(), MagicMock()]
        mock_executor._topological_sort.return_value = ["node_a", "node_b", "node_c"]

        r1 = self.runner.invoke(app, ["workflow", "validate", "/fake/wf.json"])
        self.assertEqual(r1.exit_code, 0)
        self.assertIn("格式有效", r1.output)
        self.assertIn("data_pipeline", r1.output)

        # 2. describe
        mock_node = MagicMock()
        mock_node.node_id = "node_a"
        mock_node.node_type = "sqlite_connect"
        mock_node.label = "Connect DB"

        mock_executor.workflow_name = "data_pipeline"
        mock_executor.nodes = {"node_a": mock_node}
        mock_executor.edges = [Edge("node_a", "output", "node_b", "input")]

        r2 = self.runner.invoke(app, ["workflow", "describe", "/fake/wf.json"])
        self.assertEqual(r2.exit_code, 0)
        self.assertIn("data_pipeline", r2.output)
        self.assertIn("node_a", r2.output)

    def test_workflow_list_with_workflow_scanner(self):
        """场景：列出工作流（使用真实文件系统）"""
        with tempfile.TemporaryDirectory() as _tmpdir:
            old_cwd = os.getcwd()
            os.chdir(_tmpdir)
            try:
                wf_dir = Path("workflows") / "test_scenario"
                wf_dir.mkdir(parents=True)
                (wf_dir / "workflow.json").write_text(json.dumps({
                    "workflow_name": "scenario_test",
                    "nodes": [{"id": "n1", "type": "http_request"}],
                    "edges": [],
                }))
                r = self.runner.invoke(app, ["workflow", "list"])
                self.assertEqual(r.exit_code, 0)
                self.assertIn("scenario_test", r.output)
            finally:
                os.chdir(old_cwd)


class TestCLIWorkflowEditScenario(unittest.TestCase):
    """workflow 编辑命令端到端场景"""

    def setUp(self):
        self.runner = CliRunner()

    def test_workflow_create_then_list_json(self):
        """场景：创建工作流 → list --json 可解析"""
        with tempfile.TemporaryDirectory() as _tmpdir:
            old_cwd = os.getcwd()
            os.chdir(_tmpdir)
            try:
                # 创建
                r1 = self.runner.invoke(app, ["workflow", "create", "edit_test"])
                self.assertEqual(r1.exit_code, 0)
                self.assertIn("已创建", r1.output)
                self.assertTrue(Path("workflows/edit_test/workflow.json").exists())

                # list --json
                r2 = self.runner.invoke(app, ["workflow", "list", "--json"])
                self.assertEqual(r2.exit_code, 0)
                data = json.loads(r2.output)
                self.assertIsInstance(data, list)
                self.assertEqual(len(data), 1)
                self.assertEqual(data[0]["name"], "edit_test")
            finally:
                os.chdir(old_cwd)

    def test_workflow_copy_workflow(self):
        """场景：创建工作流 → 复制 → 两个独立存在"""
        with tempfile.TemporaryDirectory() as _tmpdir:
            old_cwd = os.getcwd()
            os.chdir(_tmpdir)
            try:
                self.runner.invoke(app, ["workflow", "create", "original_wf"])

                r_copy = self.runner.invoke(app, [
                    "workflow", "copy",
                    "workflows/original_wf/workflow.json",
                    "copied_wf",
                ])
                self.assertEqual(r_copy.exit_code, 0)
                self.assertIn("已复制", r_copy.output)
                # 原始和副本都应存在
                self.assertTrue(Path("workflows/original_wf/workflow.json").exists())
                self.assertTrue(Path("workflows/copied_wf/workflow.json").exists())
            finally:
                os.chdir(old_cwd)

    def test_workflow_copy_duplicate_name(self):
        """复制到已存在的名称应报错"""
        with tempfile.TemporaryDirectory() as _tmpdir:
            old_cwd = os.getcwd()
            os.chdir(_tmpdir)
            try:
                self.runner.invoke(app, ["workflow", "create", "src"])
                self.runner.invoke(app, ["workflow", "create", "dst"])
                r = self.runner.invoke(app, [
                    "workflow", "copy",
                    "workflows/src/workflow.json",
                    "dst",
                ])
                self.assertNotEqual(r.exit_code, 0)
                self.assertIn("已存在", r.output)
            finally:
                os.chdir(old_cwd)

    def test_workflow_run_by_name(self):
        """场景：创建工作流 → run --name 执行（空工作流应成功执行）"""
        with tempfile.TemporaryDirectory() as _tmpdir:
            old_cwd = os.getcwd()
            os.chdir(_tmpdir)
            try:
                self.runner.invoke(app, ["workflow", "create", "run_by_name"])

                # run --name 应找到工作流并加载执行（空工作流执行也成功）
                r = self.runner.invoke(app, ["run", "--name", "run_by_name"])
                self.assertEqual(r.exit_code, 0)
            finally:
                os.chdir(old_cwd)

    def test_workflow_run_by_name_not_found(self):
        """run --name 不存在的名称应报错"""
        r = self.runner.invoke(app, ["run", "--name", "ghost_wf"])
        self.assertNotEqual(r.exit_code, 0)
        self.assertIn("未找到", r.output)

    def test_workflow_run_by_name_conflict_with_path(self):
        """不传 path 也不传 --name 应报错"""
        r = self.runner.invoke(app, ["run"])
        self.assertNotEqual(r.exit_code, 0)
        self.assertIn("请指定", r.output)


if __name__ == "__main__":
    unittest.main()
