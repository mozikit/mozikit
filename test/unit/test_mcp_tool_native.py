import unittest
from unittest.mock import Mock, patch

from src.core.mcp_models import MCPToolResult
from src.core.node_base import CustomNode
from src.core.workflow_executor import WorkflowExecutor
from src.core.exceptions import ErrorCode, MozikitError


class TestMCPToolNativeNode(unittest.TestCase):
    def test_executes_in_process_and_renders_arguments(self):
        executor = WorkflowExecutor("mcp-native-test")
        node = CustomNode("mcp", "mcp_tool", {
            "server_id": "demo",
            "tool_name": "echo",
            "arguments": {"summary": "Bug: {% title %}"},
        })
        node.generate_script = Mock(side_effect=AssertionError("native node scripted"))
        executor.add_node(node)
        executor.context = {"title": "Login failed"}
        service = Mock()
        service.call_tool.return_value = MCPToolResult([], {"key": "TEST-1"}, False, None)

        with patch("src.core.mcp_tool_executor.get_mcp_client_service", return_value=service):
            output, report = executor._execute_node_with_details("mcp", {})

        self.assertEqual(output["result"]["key"], "TEST-1")
        self.assertTrue(report["success"])
        self.assertEqual(report["script_path"], "")
        service.call_tool.assert_called_once_with(
            "demo", "echo", {"summary": "Bug: Login failed"}, timeout=None
        )

    def test_native_nodes_are_not_generated_as_scripts(self):
        executor = WorkflowExecutor("mcp-native-test")
        executor.add_node(CustomNode("mcp", "mcp_tool", {
            "server_id": "demo", "tool_name": "echo", "arguments": {},
        }))
        self.assertEqual(executor.generate_scripts(), {})

    def test_tool_error_fails_node_and_keeps_error_code(self):
        executor = WorkflowExecutor("mcp-native-test")
        executor.add_node(CustomNode("mcp", "mcp_tool", {
            "server_id": "demo", "tool_name": "echo", "arguments": {},
        }))
        service = Mock()
        service.call_tool.side_effect = MozikitError(ErrorCode.MCP_SERVER_DISABLED, "demo")
        with patch("src.core.mcp_tool_executor.get_mcp_client_service", return_value=service):
            _, report = executor._execute_node_with_details("mcp", {})
        self.assertFalse(report["success"])
        self.assertIn("MCP_SERVER_DISABLED", report["error"])
