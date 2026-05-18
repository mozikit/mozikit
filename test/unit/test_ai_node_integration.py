import json
import shutil
import unittest
from pathlib import Path

from src.core.config_manager import ConfigManager
from src.core.custom_node_manager import CustomNodeManager


class TestAISettingsAndGeneratedNode(unittest.TestCase):
    def setUp(self):
        self.test_root = Path("test/.tmp_ai_node_tests_ascii")
        if self.test_root.exists():
            shutil.rmtree(self.test_root)
        self.test_root.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if self.test_root.exists():
            shutil.rmtree(self.test_root)

    def test_config_manager_persists_ai_settings(self):
        config_path = self.test_root / "config.json"
        manager = ConfigManager(str(config_path))

        manager.set_ai_settings(
            {
                "base_url": "https://example.com/v1",
                "api_key": "secret",
                "model": "test-model",
                "timeout_seconds": 45,
                "temperature": 0.4,
            }
        )

        reloaded = ConfigManager(str(config_path))
        settings = reloaded.get_ai_settings()
        self.assertEqual(settings["base_url"], "https://example.com/v1")
        self.assertEqual(settings["api_key"], "secret")
        self.assertEqual(settings["model"], "test-model")
        self.assertEqual(settings["timeout_seconds"], 45)
        self.assertEqual(settings["temperature"], 0.4)

    def test_create_generated_node_writes_complete_files(self):
        manager = CustomNodeManager(self.test_root / "user_data")
        node_def = manager.create_generated_node(
            name="test_node",
            description="test description",
            source_code="def execute(self, input_data):\n    return {**input_data, 'ok': True}\n",
            config_schema={"url": {"type": "string", "label": "URL"}},
            dependencies=["requests>=2.0.0"],
        )

        self.assertIsNotNone(node_def)
        node_dir = manager.custom_nodes_dir / node_def.node_type
        self.assertTrue((node_dir / "node.json").exists())
        self.assertTrue((node_dir / "node.py").exists())

        with open(node_dir / "node.json", "r", encoding="utf-8") as f:
            config = json.load(f)

        self.assertEqual(config["name"], "test_node")
        self.assertEqual(config["dependencies"], ["requests>=2.0.0"])
        self.assertIn("url", config["config_schema"])


if __name__ == "__main__":
    unittest.main()
