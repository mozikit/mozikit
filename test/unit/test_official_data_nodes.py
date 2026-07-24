import json
import shutil
import sys
import unittest
from pathlib import Path

from src.core.node_base import NodeBase
from src.core.node_registry import get_registry
from src.core.workflow_runner import handle_run_node


class TestOfficialDataNodes(unittest.TestCase):
    def setUp(self):
        self.test_root = Path("test/.tmp_official_data_nodes")
        if self.test_root.exists():
            shutil.rmtree(self.test_root)
        self.test_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if self.test_root.exists():
            shutil.rmtree(self.test_root)

    @unittest.skip("需要 mozikit-official-nodes 仓库中的节点定义，CI 中不可用")
    def test_table_reader_reads_csv(self):
        csv_path = self.test_root / "demo.csv"
        csv_path.write_text("name,count\nalpha,1\nbeta,2\n", encoding="utf-8")

        node = NodeBase.from_dict({
            "node_id": "node_reader",
            "node_type": "table_reader",
            "config": {
                "file_path": str(csv_path),
                "file_type": "csv",
                "output_var": "table_data",
            },
        })
        script_path = node.generate_script(str(self.test_root / "scripts"))

        result = handle_run_node({"script_path": script_path, "input_data": {}})

        self.assertTrue(result["success"], result.get("error"))
        table_data = result["data"]["table_data"]
        self.assertEqual(table_data["row_count"], 2)
        self.assertEqual(table_data["columns"], ["name", "count"])
        self.assertEqual(table_data["rows"][0]["name"], "alpha")
        self.assertEqual(table_data["rows"][1]["count"], "2")

    @unittest.skip("需要 mozikit-official-nodes 仓库中的节点定义，CI 中不可用")
    def test_table_aggregate_and_template_render(self):
        aggregate_node = NodeBase.from_dict({
            "node_id": "node_aggregate",
            "node_type": "table_aggregate",
            "config": {
                "input_rows_var": "table_data",
                "filters": [{"field": "status", "op": "eq", "value": "open"}],
                "group_by": ["owner"],
                "metrics": [
                    {"metric": "count", "alias": "issue_count"},
                    {"metric": "sum", "field": "score", "alias": "score_sum"},
                ],
                "sort_by": [{"field": "issue_count", "descending": True}],
                "output_var": "aggregate_result",
            },
        })
        aggregate_script = aggregate_node.generate_script(str(self.test_root / "scripts"))
        aggregate_result = handle_run_node(
            {
                "script_path": aggregate_script,
                "input_data": {
                    "table_data": {
                        "rows": [
                            {"owner": "alice", "status": "open", "score": 3},
                            {"owner": "alice", "status": "closed", "score": 8},
                            {"owner": "bob", "status": "open", "score": 5},
                            {"owner": "bob", "status": "open", "score": 2},
                        ]
                    }
                },
            }
        )

        self.assertTrue(aggregate_result["success"], aggregate_result.get("error"))
        payload = aggregate_result["data"]["aggregate_result"]
        self.assertEqual(payload["group_count"], 2)
        self.assertEqual(payload["summary"]["filtered_row_count"], 3)
        self.assertEqual(payload["result_rows"][0]["owner"], "bob")
        self.assertEqual(payload["result_rows"][0]["issue_count"], 2)
        self.assertEqual(payload["result_rows"][0]["score_sum"], 7.0)

        template_node = NodeBase.from_dict({
            "node_id": "node_template",
            "node_type": "text_template_render",
            "config": {
                "template_text": "共 {{summary.filtered_row_count}} 条，分组数 {{group_count}}。",
                "data_var": "aggregate_result",
                "output_var": "report_text",
                "missing_key_mode": "error",
            },
        })
        template_script = template_node.generate_script(str(self.test_root / "scripts"))
        template_result = handle_run_node(
            {
                "script_path": template_script,
                "input_data": aggregate_result["data"],
            }
        )

        self.assertTrue(template_result["success"], template_result.get("error"))
        self.assertEqual(
            template_result["data"]["report_text"],
            "共 3 条，分组数 2。",
        )

    @unittest.skip("需要 mozikit-official-nodes 仓库中的节点定义，CI 中不可用")
    def test_clipboard_send_uses_clipboard_and_hotkeys(self):
        stub_dir = self.test_root / "stubs"
        stub_dir.mkdir(parents=True, exist_ok=True)
        log_path = self.test_root / "clipboard_log.json"

        (stub_dir / "pyperclip.py").write_text(
            "import json\n"
            "from pathlib import Path\n"
            f"LOG_PATH = Path({json.dumps(str(log_path), ensure_ascii=False)})\n"
            "def copy(text):\n"
            "    data = {'copied_text': text}\n"
            "    LOG_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')\n",
            encoding="utf-8",
        )
        (stub_dir / "pyautogui.py").write_text(
            "import json\n"
            "from pathlib import Path\n"
            f"LOG_PATH = Path({json.dumps(str(log_path), ensure_ascii=False)})\n"
            "def hotkey(*keys):\n"
            "    data = {}\n"
            "    if LOG_PATH.exists():\n"
            "        data = json.loads(LOG_PATH.read_text(encoding='utf-8'))\n"
            "    calls = data.setdefault('hotkeys', [])\n"
            "    calls.append(list(keys))\n"
            "    LOG_PATH.write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')\n",
            encoding="utf-8",
        )

        sys.path.insert(0, str(stub_dir))
        try:
            node = NodeBase.from_dict({
                "node_id": "node_clipboard",
                "node_type": "clipboard_send",
                "config": {
                    "text_var": "report_text",
                    "paste_hotkey": "ctrl+v",
                    "send_hotkey": "enter",
                    "output_var": "send_result",
                },
            })
            script_path = node.generate_script(str(self.test_root / "scripts"))
            result = handle_run_node(
                {"script_path": script_path, "input_data": {"report_text": "hello"}}
            )
        finally:
            sys.path.remove(str(stub_dir))

        self.assertTrue(result["success"], result.get("error"))
        send_result = result["data"]["send_result"]
        self.assertEqual(send_result["send_status"], "success")
        self.assertEqual(send_result["sent_text_length"], 5)

        log_data = json.loads(log_path.read_text(encoding="utf-8"))
        self.assertEqual(log_data["copied_text"], "hello")
        self.assertEqual(log_data["hotkeys"], [["ctrl", "v"], ["enter"]])

    @unittest.skip("需要 mozikit-official-nodes 仓库中的节点定义，CI 中不可用")
    def test_registry_exposes_new_official_nodes(self):
        registry = get_registry()
        self.assertIsNotNone(registry.get_node("table_reader"))
        self.assertIsNotNone(registry.get_node("table_aggregate"))
        self.assertIsNotNone(registry.get_node("text_template_render"))
        clipboard_node = registry.get_node("clipboard_send")
        self.assertIsNotNone(clipboard_node)
        self.assertIn("pyautogui", clipboard_node.dependencies)
        self.assertIn("pyperclip", clipboard_node.dependencies)


if __name__ == "__main__":
    unittest.main()
