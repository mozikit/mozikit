"""
CLI workflow import/export 命令单元测试
"""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from typer.testing import CliRunner

from src.cli import app


def _json_from_output(result) -> dict:
    """从 CLI 输出中提取 JSON（去除 Rich ANSI 控制字符）"""
    import re
    text = result.output
    text = re.sub(r"\x1b\[[0-9;]*[a-zA-Z]", "", text)
    text = re.sub(r"\x1b\][0-9;]*\x07", "", text)
    # 合并断行
    text = "".join(text.splitlines())
    return json.loads(text)


# ===================================================================
# 1. workflow export
# ===================================================================

class TestWorkflowExport(unittest.TestCase):
    """workflow export 命令"""

    def setUp(self):
        self.runner = CliRunner()

    @patch("src.cli._load_workflow")
    def test_export_to_stdout(self, mock_load):
        """export 不带 -o 应输出 JSON 到终端"""
        mock_executor = MagicMock()
        mock_executor.build_workflow_data.return_value = {
            "version": 2,
            "workflow_name": "test_wf",
            "nodes": [
                {"node_id": "n1", "node_type": "variable_assign", "config": {"value": "42"}}
            ],
            "edges": [],
        }
        mock_load.return_value = mock_executor

        result = self.runner.invoke(app, [
            "workflow", "export",
            "/fake/path/workflow.json",
        ])
        self.assertEqual(result.exit_code, 0)
        data = _json_from_output(result)
        self.assertEqual(data["workflow_name"], "test_wf")
        self.assertEqual(len(data["nodes"]), 1)

    @patch("src.cli._load_workflow")
    def test_export_to_file(self, mock_load):
        """export 带 -o 应写入文件"""
        mock_executor = MagicMock()
        mock_executor.build_workflow_data.return_value = {
            "version": 2,
            "workflow_name": "test_wf",
            "nodes": [],
            "edges": [],
        }
        mock_load.return_value = mock_executor

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as tmp:
            tmp_path = tmp.name

        try:
            result = self.runner.invoke(app, [
                "workflow", "export",
                "/fake/path/workflow.json",
                "--output", tmp_path,
            ])
            self.assertEqual(result.exit_code, 0)
            self.assertIn("已导出", result.output)

            with open(tmp_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.assertEqual(data["workflow_name"], "test_wf")
        finally:
            os.unlink(tmp_path)

    @patch("src.cli._load_workflow")
    def test_export_data_integrity(self, mock_load):
        """export 应保留完整的节点/连接结构"""
        mock_executor = MagicMock()
        mock_executor.build_workflow_data.return_value = {
            "version": 2,
            "workflow_name": "integrity_test",
            "nodes": [
                {"node_id": "n1", "node_type": "text_template_render", "config": {"template_text": "Hello"}},
                {"node_id": "n2", "node_type": "text_template_render", "config": {"template_text": "World"}},
            ],
            "edges": [
                {"from_node": "n1", "from_port": "output", "to_node": "n2", "to_port": "input"},
            ],
            "dependencies": [],
        }
        mock_load.return_value = mock_executor

        result = self.runner.invoke(app, [
            "workflow", "export",
            "/fake/path/workflow.json",
        ])
        self.assertEqual(result.exit_code, 0)
        data = _json_from_output(result)
        self.assertEqual(len(data["nodes"]), 2)
        self.assertEqual(len(data["edges"]), 1)
        self.assertEqual(data["edges"][0]["from_node"], "n1")


# ===================================================================
# 2. workflow import
# ===================================================================

class TestWorkflowImport(unittest.TestCase):
    """workflow import 命令"""

    def setUp(self):
        self.runner = CliRunner()

    @patch("src.cli.WorkflowExecutor.load_workflow")
    @patch("src.cli.os.makedirs")
    @patch("src.cli.resolve_workspace")
    def test_import_success(self, mock_ws, mock_makedirs, mock_load):
        """import 有效 JSON 应创建工作流"""
        mock_executor = MagicMock()
        mock_executor.nodes = {"n1": MagicMock()}
        mock_executor.edges = []
        mock_executor.workflow_name = "imported_wf"
        mock_load.return_value = mock_executor

        mock_ws.return_value = Path("/tmp/test_ws")

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump({"workflow_name": "imported_wf", "nodes": [], "edges": []}, f)
            src_path = f.name

        try:
            result = self.runner.invoke(app, [
                "workflow", "import",
                src_path,
            ])
            self.assertEqual(result.exit_code, 0)
            self.assertIn("已导入", result.output)
            self.assertIn("imported_wf", result.output)
        finally:
            os.unlink(src_path)

    def test_import_file_not_found(self):
        """import 不存在的文件应报错"""
        result = self.runner.invoke(app, [
            "workflow", "import",
            "/nonexistent/path/workflow.json",
        ])
        self.assertNotEqual(result.exit_code, 0)
        self.assertIn("不存在", result.output)

    def test_import_invalid_json(self):
        """import 无效 JSON 应报错"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            f.write("这不是 JSON {{{{")
            src_path = f.name

        try:
            result = self.runner.invoke(app, [
                "workflow", "import",
                src_path,
            ])
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("JSON", result.output)
        finally:
            os.unlink(src_path)

    @patch("src.cli.resolve_workspace")
    def test_import_without_name_and_json_has_no_name(self, mock_ws):
        """import 未提供名称且 JSON 中无 workflow_name 应报错"""
        mock_ws.return_value = Path("/tmp/test_ws")

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump({"nodes": [], "edges": []}, f)
            src_path = f.name

        try:
            result = self.runner.invoke(app, [
                "workflow", "import",
                src_path,
            ])
            self.assertNotEqual(result.exit_code, 0)
            self.assertIn("名称", result.output)
        finally:
            os.unlink(src_path)

    @patch("src.cli.WorkflowExecutor.load_workflow")
    @patch("src.cli.resolve_workspace")
    def test_import_with_name_override(self, mock_ws, mock_load):
        """import --name 应覆盖 JSON 中的 workflow_name"""
        mock_executor = MagicMock()
        mock_executor.nodes = {}
        mock_executor.edges = []
        mock_executor.workflow_name = "original_name"
        mock_load.return_value = mock_executor

        mock_ws.return_value = Path("/tmp/test_ws")

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump({"workflow_name": "original_name", "nodes": [], "edges": []}, f)
            src_path = f.name

        try:
            result = self.runner.invoke(app, [
                "workflow", "import",
                src_path,
                "--name", "renamed_flow",
            ])
            self.assertEqual(result.exit_code, 0)
            self.assertIn("renamed_flow", result.output)
        finally:
            os.unlink(src_path)

    @patch("src.cli.WorkflowExecutor.load_workflow")
    @patch("src.cli.os.makedirs")
    @patch("src.cli.resolve_workspace")
    def test_import_shows_node_edge_count(self, mock_ws, mock_makedirs, mock_load):
        """import 应显示节点数和连接数"""
        mock_executor = MagicMock()
        mock_executor.nodes = {"n1": MagicMock(), "n2": MagicMock()}
        mock_executor.edges = [MagicMock()]
        mock_executor.workflow_name = "count_test"
        mock_load.return_value = mock_executor

        mock_ws.return_value = Path("/tmp/test_ws")

        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False, encoding="utf-8"
        ) as f:
            json.dump({"workflow_name": "count_test", "nodes": [], "edges": []}, f)
            src_path = f.name

        try:
            result = self.runner.invoke(app, [
                "workflow", "import",
                src_path,
            ])
            self.assertEqual(result.exit_code, 0)
            self.assertIn("2", result.output)   # 2 nodes
            self.assertIn("1", result.output)   # 1 edge
        finally:
            os.unlink(src_path)


# ===================================================================
# 3. 帮助信息中包含新命令
# ===================================================================

class TestCLIHelpContainsNewCommands(unittest.TestCase):
    """验证 export/import 出现在帮助中"""

    def setUp(self):
        self.runner = CliRunner()

    def test_workflow_help_contains_export_import(self):
        result = self.runner.invoke(app, ["workflow", "--help"])
        self.assertEqual(result.exit_code, 0)
        self.assertIn("export", result.output)
        self.assertIn("import", result.output)


if __name__ == "__main__":
    unittest.main()
