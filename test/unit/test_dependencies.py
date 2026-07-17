
import unittest
from unittest.mock import MagicMock, patch
from pathlib import Path
from src.core.workflow_executor import WorkflowExecutor
from src.core.node_base import NodeBase, NodeType

class TestDependencyPassing(unittest.TestCase):
    def setUp(self):
        self.uv_manager = MagicMock()
        self.executor = WorkflowExecutor("test_workflow", self.uv_manager)

    @patch('src.core.node_registry.get_registry')
    def test_collect_dependencies(self, mock_get_registry):
        # Mock Registry
        mock_registry = MagicMock()
        mock_get_registry.return_value = mock_registry
        
        # Mock Node Definitions with dependencies
        node_def_1 = MagicMock()
        node_def_1.dependencies = ["requests>=2.25.1", "pandas"]
        node_def_2 = MagicMock()
        node_def_2.dependencies = ["requests<=2.28.0", "numpy"]
        
        def get_node_def(node_type):
            if node_type == "type1": return node_def_1
            if node_type == "type2": return node_def_2
            return None
            
        mock_registry.get_node.side_effect = get_node_def
        
        # Add mock nodes to executor
        node1 = MagicMock(spec=NodeBase)
        node1.node_type = "type1"
        node1.node_id = "node1"
        
        node2 = MagicMock(spec=NodeBase)
        node2.node_type = "type2"
        node2.node_id = "node2"
        
        self.executor.nodes = {"node1": node1, "node2": node2}
        
        # Test collection
        deps = self.executor._collect_node_dependencies()
        self.assertIn("requests>=2.25.1", deps)
        self.assertIn("pandas", deps)
        self.assertIn("requests<=2.28.0", deps)
        self.assertIn("numpy", deps)
        
        # Test resolution (deduplication)
        resolved = self.executor._resolve_dependencies(deps)
        # requests exists twice with different versions, both should be in cleaned list for now 
        # (our resolution only deduplicates exact matches, but warns on conflicts)
        self.assertEqual(len(resolved), 4)

    @patch.object(WorkflowExecutor, '_collect_node_dependencies')
    @patch.object(WorkflowExecutor, '_resolve_dependencies')
    def test_prepare_environment_calls_install(self, mock_resolve, mock_collect):
        mock_collect.return_value = ["pkg1"]
        mock_resolve.return_value = ["pkg1"]
        self.uv_manager.create_workflow_env.return_value = True
        self.uv_manager.install_packages.return_value = True
        
        success = self.executor.prepare_environment()
        
        self.assertTrue(success)
        self.uv_manager.install_packages.assert_called_with("test_workflow", ["pkg1"])

    def test_execute_node_supports_string_node_type(self):
        workspace = Path("test/.tmp_execute_node")
        workspace.mkdir(parents=True, exist_ok=True)

        node = MagicMock(spec=NodeBase)
        node.node_type = "custom_csv_processor"
        node.node_id = "node1"
        node.config = {}
        node.generate_script.return_value = str(workspace / "node1.py")

        self.executor.nodes = {"node1": node}
        self.uv_manager.get_workflow_dir.return_value = workspace
        self.uv_manager.run_python_script_streaming.return_value = {
            "success": True,
            "data": {"ok": True},
            "error": "",
            "output": "",
        }

        result = self.executor.execute_node("node1", {"path": "demo.csv"})

        self.assertEqual(result, {"ok": True})
        self.uv_manager.run_python_script_streaming.assert_called_once()

if __name__ == '__main__':
    unittest.main()
