
import unittest
import shutil
import json
import os
from pathlib import Path
from src.core.node_registry import get_registry, NodeSource
from src.core.workflow_executor import WorkflowExecutor
from src.core.custom_node_manager import CustomNodeManager
from src.core.providers.github_provider import GitHubNodeProvider
from src.core.node_base import NodeBase

class TestNodeFeaturesIntegration(unittest.TestCase):
    def setUp(self):
        # Setup temporary environment
        self.test_dir = Path("user_data_integration_test")
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)
        self.test_dir.mkdir(parents=True)
        
        # Patch registry to use test directory
        self.registry = get_registry()
        self.registry._user_data_dir = self.test_dir
        self.registry._nodes = {} # Clear existing
        self.registry._load_official_nodes()
        
    def tearDown(self):
        if self.test_dir.exists():
            shutil.rmtree(self.test_dir)

    def test_full_lifecycle_flow(self):
        # 1. Create a Custom Node with dependencies
        custom_manager = CustomNodeManager(self.test_dir)
        custom_node_def = custom_manager.create_node("My Processing Node", "Process some data")
        self.assertIsNotNone(custom_node_def)
        
        # Add dependency to custom node
        custom_node_def.dependencies = ["pandas", "openpyxl"]
        self.registry.register_external_node(custom_node_def)
        
        # 2. Import a GitHub Node
        github_provider = GitHubNodeProvider(self.test_dir)
        github_url = "https://github.com/example/api-node"
        github_node_def = github_provider.download_node(github_url)
        self.assertIsNotNone(github_node_def)
        
        # GitHub node mock info in provider has 'requests' as dependency
        self.assertIn("requests", github_node_def.dependencies)
        
        # 3. Build a Workflow
        executor = WorkflowExecutor("IntegrationFlow")
        
        # Instantiate nodes from registry definitions
        node1 = NodeBase.from_dict({
            "node_id": "custom_1",
            "node_type": custom_node_def.node_type,
            "config": {"param": "value"}
        })
        node2 = NodeBase.from_dict({
            "node_id": "github_1",
            "node_type": github_node_def.node_type,
            "config": {"api_key": "secret"}
        })
        
        executor.add_node(node1)
        executor.add_node(node2)
        executor.add_edge("github_1", "custom_1")
        
        # 4. Verify Dependency Collection
        deps = executor._collect_node_dependencies()
        self.assertIn("pandas", deps)
        self.assertIn("openpyxl", deps)
        self.assertIn("requests", deps)
        
        resolved_deps = executor._resolve_dependencies(deps)
        self.assertEqual(len(resolved_deps), 3)
        self.assertEqual(resolved_deps, sorted(["pandas", "openpyxl", "requests"]))
        
        # 5. Verify Script Generation
        # This checks if CustomNode correctly retrieves source_code and generates a valid script
        workflow_dir = executor.uv_manager.get_workflow_dir("IntegrationFlow")
        scripts_dir = workflow_dir / "scripts"
        
        script_paths = executor.generate_scripts()
        self.assertIn("custom_1", script_paths)
        self.assertIn("github_1", script_paths)
        
        for path in script_paths.values():
            self.assertTrue(os.path.exists(path))
            with open(path, 'r', encoding='utf-8') as f:
                content = f.read()
                self.assertIn("import json", content)
                self.assertIn("def execute", content)
                self.assertIn("NODE_CONFIG", content)

        print("集成测试全部通过: 节点创建、导入、依赖收集、脚本生成。")

if __name__ == '__main__':
    unittest.main()
