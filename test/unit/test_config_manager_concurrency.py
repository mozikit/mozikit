import shutil
import unittest
from pathlib import Path

from src.core.config_manager import ConfigManager


class TestConfigManagerConcurrency(unittest.TestCase):
    def setUp(self):
        self.test_root = Path("test/.tmp_config_manager_concurrency")
        if self.test_root.exists():
            shutil.rmtree(self.test_root)
        self.test_root.mkdir(parents=True, exist_ok=True)
        self.config_path = self.test_root / "config.json"

    def tearDown(self):
        if self.test_root.exists():
            shutil.rmtree(self.test_root)

    def test_multiple_instances_do_not_overwrite_ai_settings(self):
        manager_a = ConfigManager(str(self.config_path))
        manager_b = ConfigManager(str(self.config_path))

        # save_config 默认是异步后台线程，替换为同步版本避免竞争
        manager_b.save_config = manager_b.save_config_sync
        manager_a.save_config = manager_a.save_config_sync

        manager_b.set_ai_settings(
            {
                "base_url": "https://integrate.api.nvidia.com",
                "api_key": "nvapi-test",
                "model": "minimaxai/minimax-m2.5",
                "timeout_seconds": 90,
                "temperature": 0.1,
            }
        )

        manager_a.set_window_geometry(1, 2, 3, 4)
        manager_a.save_config_sync()

        reloaded = ConfigManager(str(self.config_path))
        settings = reloaded.get_ai_settings()

        self.assertEqual(settings["base_url"], "https://integrate.api.nvidia.com")
        self.assertEqual(settings["api_key"], "nvapi-test")
        self.assertEqual(settings["model"], "minimaxai/minimax-m2.5")
        self.assertEqual(reloaded.get_window_geometry()["width"], 3)


if __name__ == "__main__":
    unittest.main()
