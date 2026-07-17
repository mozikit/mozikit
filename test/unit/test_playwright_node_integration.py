import shutil
import unittest
from pathlib import Path

from src.core.node_base import NodeBase, NodeType, CustomNode
from src.core.node_registry import NodeSource, get_registry
from src.core.playwright_node_utils import (
    build_playwright_config_schema,
    build_playwright_default_config,
)
from src.core.workflow_runner import handle_run_node


@unittest.skip("需要 mozikit-official-nodes 仓库中的 playwright_script 节点定义，CI 中不可用")
class TestPlaywrightNodeIntegration(unittest.TestCase):
    def setUp(self):
        self.test_root = Path("test/.tmp_playwright_nodes")
        if self.test_root.exists():
            shutil.rmtree(self.test_root)
        self.test_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if self.test_root.exists():
            shutil.rmtree(self.test_root)

    def test_registry_exposes_official_playwright_node(self):
        node_def = get_registry().get_node(NodeType.PLAYWRIGHT_SCRIPT)
        self.assertIsNotNone(node_def)
        self.assertEqual(node_def.source, NodeSource.OFFICIAL)
        self.assertEqual(node_def.metadata.get("node_kind"), "playwright_script")
        self.assertIn("playwright_timeout_seconds", node_def.config_schema)

    def test_build_default_config_contains_runtime_fields(self):
        config = build_playwright_default_config()
        self.assertEqual(config["script_source"], "")
        self.assertIn("param_schema", config)
        self.assertIn("playwright_headless", config)
        self.assertIn("playwright_timeout_seconds", config)

    def test_nodebase_from_dict_builds_playwright_runtime_node(self):
        node = NodeBase.from_dict(
            {
                "node_id": "node_1",
                "node_type": NodeType.PLAYWRIGHT_SCRIPT.value,
                "config": {"script_source": "lf_set_output({'ok': True})"},
            }
        )
        self.assertIsInstance(node, CustomNode)
        self.assertEqual(node.node_type, NodeType.PLAYWRIGHT_SCRIPT)

    def test_playwright_node_executes_embedded_script_from_config(self):
        config = build_playwright_default_config(
            {
                "script_source": (
                    "from pathlib import Path\n"
                    "download_path = Path(LF_DOWNLOAD_DIR) / 'daily.xlsx'\n"
                    "download_path.write_text('ok', encoding='utf-8')\n"
                    "artifact_path = Path(LF_ARTIFACTS_DIR) / 'trace.txt'\n"
                    "artifact_path.write_text('trace', encoding='utf-8')\n"
                    "lf_add_artifact('trace', artifact_path)\n"
                    "lf_set_output({\n"
                    "    'url': '{{url}}',\n"
                    "    'limit': {{limit}},\n"
                    "    'flag': LF_INPUT_DATA.get('flag')\n"
                    "})\n"
                ),
                "param_schema": build_playwright_config_schema(["url", "limit"]),
                "url": "https://example.com",
                "limit": 3,
                "playwright_headless": True,
                "playwright_timeout_seconds": 5,
            }
        )
        node = NodeBase.from_dict({
            "node_id": "node_playwright",
            "node_type": "playwright_script",
            "config": config,
        })
        script_path = node.generate_script(str(self.test_root / "scripts"))

        result = handle_run_node(
            {"script_path": script_path, "input_data": {"flag": True}}
        )

        self.assertTrue(result["success"], result.get("error"))
        data = result["data"]
        self.assertTrue(data["flag"])
        self.assertEqual(data["structured_output"]["url"], "https://example.com")
        self.assertEqual(data["structured_output"]["limit"], 3)
        self.assertTrue(data["structured_output"]["flag"])
        self.assertEqual(len(data["downloads"]), 1)
        self.assertTrue(data["downloads"][0].endswith("daily.xlsx"))
        self.assertIn("trace", data["artifacts"])
        self.assertTrue(data["meta"]["headless"])

    def test_playwright_node_requires_script_before_execute(self):
        node = NodeBase.from_dict({
            "node_id": "node_playwright",
            "node_type": "playwright_script",
            "config": {},
        })
        script_path = node.generate_script(str(self.test_root / "scripts"))

        result = handle_run_node({"script_path": script_path, "input_data": {}})

        self.assertFalse(result["success"])
        self.assertIn("请先在节点详情中配置 Playwright 脚本", result["error"])


if __name__ == "__main__":
    unittest.main()
