
import unittest
import shutil
from unittest.mock import patch
from pathlib import Path
from src.core.providers.github_provider import GitHubNodeProvider
from src.core.node_registry import NodeSource, get_registry

class TestGitHubProvider(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = Path("user_data_test")
        self.tmp_dir.mkdir(parents=True, exist_ok=True)
        self.provider = GitHubNodeProvider(self.tmp_dir)
        self.registry = get_registry()
        # Override user_data_dir for test
        self.registry._user_data_dir = self.tmp_dir

    def tearDown(self):
        if self.tmp_dir.exists():
            shutil.rmtree(self.tmp_dir)

    def test_parse_url(self):
        cases = [
            ("https://github.com/owner/repo", ("owner", "repo")),
            ("owner/repo", ("owner", "repo")),
            ("https://github.com/owner/repo.git", ("owner", "repo")),
            ("invalid-url", None),
        ]
        for url, expected in cases:
            with self.subTest(url=url):
                result = self.provider.parse_url(url)
                self.assertEqual(result, expected)

    def test_parse_url_info_supports_subdir_urls(self):
        result = self.provider.parse_url_info("https://github.com/owner/repo/tree/main/public_demo")
        self.assertEqual(result, ("owner", "repo", "public_demo"))

    @patch("src.core.providers.github_provider.get_registry")
    @patch("src.core.providers.github_provider._gh_get")
    def test_download_manifest_repo_nodes(self, mock_gh_get, mock_get_registry):
        url = "https://github.com/test_owner/test_repo"
        mock_get_registry.return_value = self.registry

        def side_effect(request_url, token=None, timeout=15):
            if request_url.endswith("/contents/node.json"):
                return 404, {}
            if request_url.endswith("/contents/manifest.json"):
                return 200, {
                    "content": "ewogICJub2RlcyI6IFsicHVibGljX2RlbW8iXQp9"
                }
            if request_url.endswith("/contents/public_demo/node.json"):
                return 200, {
                    "content": (
                        "ewogICJub2RlX3R5cGUiOiAicHVibGljX2RlbW8iLAogICJuYW1lIjogInB1YmxpYy1kZW1vIiwK"
                        "ICAiZGVzY3JpcHRpb24iOiAiZGVtbyIsCiAgImNhdGVnb3J5IjogIlNob3djYXNlIiwKICAiZW50"
                        "cnlfZmlsZSI6ICJub2RlLnB5IiwKICAiZGVwZW5kZW5jaWVzIjogW10sCiAgImNvbmZpZ19zY2hl"
                        "bWEiOiB7fQp9"
                    )
                }
            if request_url.endswith("/contents/public_demo/node.py"):
                return 200, {
                    "content": "ZGVmIGV4ZWN1dGUoc2VsZiwgaW5wdXRfZGF0YSk6CiAgICByZXR1cm4geyoqaW5wdXRfZGF0YSwgIm9rIjogVHJ1ZX0K"
                }
            return 404, {}

        mock_gh_get.side_effect = side_effect

        node_defs = self.provider.download_nodes(url)

        self.assertEqual(len(node_defs), 1)
        node_def = node_defs[0]
        self.assertEqual(node_def.source, NodeSource.GITHUB)
        self.assertEqual(node_def.repo_url, url)
        self.assertEqual(node_def.node_type, "public_demo")

        node_path = self.tmp_dir / "external_nodes" / "github" / "test_owner" / "test_repo" / "public_demo"
        self.assertTrue((node_path / "node.json").exists())
        self.assertTrue((node_path / "node.py").exists())
        self.assertIn(node_def.node_type, self.registry._nodes)

        success = self.provider.delete_node(node_def.node_type)
        self.assertTrue(success)
        self.assertFalse(node_path.exists())
        self.assertNotIn(node_def.node_type, self.registry._nodes)

if __name__ == '__main__':
    unittest.main()
