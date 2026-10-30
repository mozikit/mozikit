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

class TestWorkflowImport:
    def setup_method(self):
        self.runner = CliRunner()

    def fixture(self, tmp_path, monkeypatch, data=None):
        workspace = tmp_path / 'workspace'
        monkeypatch.setenv('MOZIKIT_WORKSPACE', str(workspace))
        monkeypatch.setenv('MOZIKIT_APP_DATA_DIR', str(tmp_path / 'data'))
        source = tmp_path / 'input.json'
        document = {'workflow_name': 'imported_wf', 'nodes': [], 'edges': []} if data is None else data
        source.write_text(json.dumps(document), encoding='utf-8')
        return source, workspace

    def test_import_success(self, tmp_path, monkeypatch):
        source, workspace = self.fixture(tmp_path, monkeypatch)
        result = self.runner.invoke(app, ['workflow','import',str(source)])
        assert result.exit_code == 0, result.output
        assert (workspace/'imported_wf'/'workflow.json').is_file()

    def test_import_file_not_found(self, tmp_path, monkeypatch):
        source, workspace = self.fixture(tmp_path, monkeypatch)
        source.unlink()
        result = self.runner.invoke(app, ['workflow','import',str(source)])
        assert result.exit_code == 1 and '不存在' in result.output

    def test_import_invalid_json(self, tmp_path, monkeypatch):
        source, workspace = self.fixture(tmp_path, monkeypatch)
        source.write_text('invalid {{{', encoding='utf-8')
        result = self.runner.invoke(app, ['workflow','import',str(source)])
        assert result.exit_code == 1 and 'JSON' in result.output
        assert not (workspace/'imported_wf').exists()

    def test_import_without_name_and_json_has_no_name(self, tmp_path, monkeypatch):
        source, workspace = self.fixture(tmp_path, monkeypatch, {'nodes':[], 'edges':[]})
        result = self.runner.invoke(app, ['workflow','import',str(source)])
        assert result.exit_code == 1 and '名称' in result.output

    def test_import_with_name_override(self, tmp_path, monkeypatch):
        source, workspace = self.fixture(tmp_path, monkeypatch)
        result = self.runner.invoke(app, ['workflow','import',str(source),'--name','renamed_flow'])
        assert result.exit_code == 0, result.output
        document = json.loads((workspace/'renamed_flow'/'workflow.json').read_text())
        assert document['workflow_name'] == 'renamed_flow' and document['active'] is False

    def test_import_shows_node_edge_count(self, tmp_path, monkeypatch):
        data={'workflow_name':'count_test','nodes':[
            {'node_id':'a','node_type':'debug','config':{}},
            {'node_id':'b','node_type':'debug','config':{}}], 'edges':[['a','b']]}
        source, workspace = self.fixture(tmp_path, monkeypatch, data)
        result = self.runner.invoke(app, ['workflow','import',str(source)])
        assert result.exit_code == 0, result.output
        assert '节点: 2, 连接: 1' in result.output


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
