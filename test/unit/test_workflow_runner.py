import shutil
import unittest
from pathlib import Path

from src.core.workflow_runner import handle_run_node


class TestWorkflowRunner(unittest.TestCase):
    def setUp(self):
        self.test_root = Path("test/.tmp_workflow_runner")
        if self.test_root.exists():
            shutil.rmtree(self.test_root)
        self.test_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if self.test_root.exists():
            shutil.rmtree(self.test_root)

    def test_handle_run_node_supports_single_arg_execute(self):
        script_path = self.test_root / "single_arg.py"
        script_path.write_text(
            "def execute(input_data):\n"
            "    return {'seen': input_data.get('value')}\n",
            encoding="utf-8",
        )

        result = handle_run_node(
            {"script_path": str(script_path), "input_data": {"value": 123}}
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["seen"], 123)

    def test_handle_run_node_supports_self_and_input_data_execute(self):
        script_path = self.test_root / "custom_arg.py"
        script_path.write_text(
            "NODE_CONFIG = {'file_path': 'demo.csv'}\n"
            "def execute(self, input_data):\n"
            "    return {'path': self.config['file_path'], 'upstream': input_data.get('ok')}\n",
            encoding="utf-8",
        )

        result = handle_run_node(
            {"script_path": str(script_path), "input_data": {"ok": True}}
        )

        self.assertTrue(result["success"])
        self.assertEqual(result["data"]["path"], "demo.csv")
        self.assertTrue(result["data"]["upstream"])


if __name__ == "__main__":
    unittest.main()
