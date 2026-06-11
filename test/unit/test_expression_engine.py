"""
表达式引擎单元测试 — Jinja2 沙箱渲染

测试覆盖：
- render_expressions 核心逻辑（字符串/字典/列表/透传）
- 缺失引用降级（SilentUndefined）
- 凭证占位符兼容性
- Sandbox 安全隔离
- Jinja2 不可用时的降级行为
- integration: 在 WorkflowExecutor 中的调用
"""

import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch, MagicMock

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from src.core.expression_engine import render_expressions, HAS_JINJA2


# ===========================================================================
# render_expressions 单元测试
# ===========================================================================

class TestRenderExpressions(unittest.TestCase):
    """render_expressions 核心逻辑"""

    def setUp(self):
        self.ctx = {
            "greeting": "World",
            "count": 42,
            "pi": 3.14,
            "flag": True,
            "nothing": None,
            "nested": {"key": "deep", "list": [1, 2]},
        }

    # ── 基本字符串渲染 ─────────────────────────────────────────

    def test_simple_string(self):
        result = render_expressions("Hello {% greeting %}!", self.ctx)
        self.assertEqual(result, "Hello World!")

    def test_numeric_value(self):
        result = render_expressions("Count: {% count %}", self.ctx)
        self.assertEqual(result, "Count: 42")

    def test_dotted_path(self):
        result = render_expressions("{% nested.key %}", self.ctx)
        self.assertEqual(result, "deep")

    def test_multiple_expressions(self):
        result = render_expressions(
            "{% greeting %} / {% count %} / {% nested.key %}",
            self.ctx,
        )
        self.assertEqual(result, "World / 42 / deep")

    # ── 字典和列表递归 ─────────────────────────────────────────

    def test_dict_value(self):
        result = render_expressions(
            {"title": "{% greeting %}", "num": 99},
            self.ctx,
        )
        self.assertEqual(result["title"], "World")
        self.assertEqual(result["num"], 99)

    def test_nested_dict(self):
        result = render_expressions(
            {"outer": {"inner": "{% greeting %}"}},
            self.ctx,
        )
        self.assertEqual(result["outer"]["inner"], "World")

    def test_list_value(self):
        result = render_expressions(
            ["{% greeting %}", "static"],
            self.ctx,
        )
        self.assertEqual(result, ["World", "static"])

    def test_list_of_dicts(self):
        result = render_expressions(
            [{"name": "{% greeting %}"}, {"name": "static"}],
            self.ctx,
        )
        self.assertEqual(result[0]["name"], "World")

    def test_empty_structures(self):
        self.assertEqual(render_expressions({}, self.ctx), {})
        self.assertEqual(render_expressions([], self.ctx), [])

    # ── 非字符串透传 ─────────────────────────────────────────

    def test_primitive_passthrough(self):
        for val in [42, 3.14, True, False, None, b"binary"]:
            with self.subTest(val=repr(val)):
                self.assertEqual(render_expressions(val, self.ctx), val)

    # ── 不含定界符的字符串 ────────────────────────────────────

    def test_plain_string_unchanged(self):
        self.assertEqual(render_expressions("Hello World", self.ctx), "Hello World")
        self.assertEqual(render_expressions("", self.ctx), "")

    # ── 缺失引用降级（SilentUndefined） ─────────────────────

    def test_missing_key_returns_empty(self):
        self.assertEqual(render_expressions("{% not_there %}", self.ctx), "")

    def test_missing_nested_returns_empty(self):
        self.assertEqual(render_expressions("{% missing.deep %}", self.ctx), "")

    def test_missing_in_middle_returns_partial(self):
        self.assertEqual(
            render_expressions("Hello {% missing %} World", self.ctx),
            "Hello  World",
        )

    # ── 凭证占位符兼容性 ────────────────────────────────────

    def test_credential_placeholder_untouched(self):
        result = render_expressions(
            "{{credential.github_token}}", self.ctx
        )
        self.assertEqual(result, "{{credential.github_token}}")

    def test_mixed_credential_and_expression(self):
        result = render_expressions(
            "User: {% greeting %}, Token: {{credential.github_token}}",
            self.ctx,
        )
        self.assertIn("World", result)
        self.assertIn("{{credential.github_token}}", result)

    # ── Sandbox 安全隔离 ────────────────────────────────────

    def test_sandbox_uses_sandboxed_environment(self):
        from jinja2.sandbox import SandboxedEnvironment
        from src.core.expression_engine import _EXPR_ENV
        self.assertIsInstance(_EXPR_ENV, SandboxedEnvironment)

    def test_sandbox_blocks_unsafe_attributes(self):
        """危险属性访问应被阻止（返回空字符串 或 抛出 SecurityError）"""
        from jinja2.exceptions import SecurityError
        for attr in ["__class__", "__base__", "__globals__"]:
            with self.subTest(attr=attr):
                try:
                    result = render_expressions(
                        f"{{% greeting.{attr} %}}", self.ctx
                    )
                    self.assertEqual(result, "")
                except SecurityError:
                    pass  # 抛 SecurityError 说明 Sandbox 在工作

    # ── 上下文为空的边界情况 ────────────────────────────────

    def test_empty_context(self):
        self.assertEqual(render_expressions("{% x %}", {}), "")

    def test_context_str_key(self):
        self.assertEqual(
            render_expressions("{% item %}", {"item": "val"}), "val"
        )

    # ── 多层嵌套深度遍历 ──────────────────────────────────────

    def test_deeply_nested_structure(self):
        data = {"l1": {"l2": {"l3": "{% greeting %}"}}}
        result = render_expressions(data, self.ctx)
        self.assertEqual(result["l1"]["l2"]["l3"], "World")

    def test_mixed_types_all_rendered(self):
        data = {
            "s": "Hello {% greeting %}",
            "i": 99,
            "f": 1.5,
            "b": False,
            "none": None,
            "lst": ["{% greeting %}", 42],
            "dct": {"inner": "{% count %}"},
        }
        result = render_expressions(data, self.ctx)
        self.assertEqual(result["s"], "Hello World")
        self.assertEqual(result["lst"][0], "World")
        self.assertEqual(result["dct"]["inner"], "42")


# ===========================================================================
# Jinja2 不可用降级测试
# ===========================================================================

class TestFallbackWithoutJinja2(unittest.TestCase):
    """HAS_JINJA2=False 时 render_expressions 直接返回原值"""

    @unittest.skipUnless(HAS_JINJA2, "需要 Jinja2")
    @patch("src.core.expression_engine.HAS_JINJA2", False)
    def test_returns_original_when_jinja2_unavailable(self):
        ctx = {"x": "val"}
        self.assertEqual(render_expressions("{% x %}", ctx), "{% x %}")
        self.assertEqual(
            render_expressions({"k": "{% x %}"}, ctx), {"k": "{% x %}"}
        )
        self.assertEqual(render_expressions(42, ctx), 42)


# ===========================================================================
# WorkflowExecutor 集成测试
# ===========================================================================

class TestRendererInExecutor(unittest.TestCase):
    """验证 render_expressions 在 WorkflowExecutor 中被正确集成"""

    def setUp(self):
        self.ctx = {"base": "https://example.com", "greeting": "Hello"}

    def test_executor_imports_render_expressions(self):
        from src.core import workflow_executor as we
        self.assertTrue(hasattr(we, "render_expressions"))

    def test_render_expressions_signature_works_with_input_data(self):
        """验证 render_expressions 签名兼容 executor 的调用方式"""
        input_data = {"url": "{% base %}/api", "static": "fixed"}
        result = render_expressions(input_data, self.ctx)
        self.assertEqual(result["url"], "https://example.com/api")
        self.assertEqual(result["static"], "fixed")

    def test_execute_node_renders_input_data(self):
        """
        验证 execute_node() 对 input_data 中的 {% %} 做渲染。
        这是公共 API 的入口，必须与 execute() 的渲染行为一致。
        """
        from src.core.workflow_executor import WorkflowExecutor

        executor = WorkflowExecutor("test_wf")
        executor.context = dict(self.ctx)
        executor.uv_manager = MagicMock()
        executor.uv_manager.get_workflow_dir.return_value = Path(".")

        with patch.object(executor, "_execute_node_with_details") as mock_exec:
            mock_exec.return_value = ({"ok": True}, {"success": True, "node_id": "n1"})

            executor.execute_node(
                "n1",
                input_data={"url": "{% base %}/api"},
            )

            called_input = mock_exec.call_args[0][1]
            self.assertEqual(called_input["url"], "https://example.com/api")

    def test_execute_node_handles_none_input(self):
        """execute_node 在 input_data 为 None 时不崩溃"""
        from src.core.workflow_executor import WorkflowExecutor

        executor = WorkflowExecutor("test_wf")
        executor.context = {}
        executor.uv_manager = MagicMock()
        executor.uv_manager.get_workflow_dir.return_value = Path(".")

        with patch.object(executor, "_execute_node_with_details") as mock_exec:
            mock_exec.return_value = ({}, {"success": True, "node_id": "n1"})

            # 不应抛出 TypeError
            executor.execute_node("n1", input_data=None)

    def test_execute_loop_renders_input_data(self):
        """
        验证 execute() 的渲染路径：
        _build_node_input 返回的数据中 {% %} 被渲染后才传入 _execute_node_with_details。
        """
        from src.core.workflow_executor import WorkflowExecutor

        executor = WorkflowExecutor("test_wf")
        executor._stop_event = MagicMock()
        executor._stop_event.is_set.return_value = False
        executor.uv_manager = MagicMock()
        executor.uv_manager.get_workflow_dir.return_value = Path(".")
        executor.uv_manager.start_worker.return_value = None

        from src.core.node_base import NodeBase
        node = NodeBase.from_dict({
            "node_id": "n1",
            "node_type": "variable_assign",
            "config": {"variable_name": "out", "value": "init"},
            "inputs": [],
            "outputs": [],
        })
        executor.add_node(node)

        with patch.object(executor, "generate_scripts", return_value=[]), \
             patch.object(executor, "_execute_node_with_details") as mock_exec:

            mock_exec.return_value = (
                {"out": "val"},
                {"success": True, "node_id": "n1"},
            )

            executor.execute(
                initial_data={"greeting": "Hello", "message": "{% greeting %}"},
                return_report=True,
                trigger_type="cli",
            )

            called_input = mock_exec.call_args[0][1]
            self.assertEqual(called_input["message"], "Hello")

    def test_config_expressions_injected_into_input_data(self):
        """
        验证 _execute_node_with_details 将 node.config 中渲染后的 {% %} 值注入 input_data。
        通过 mock 阻止实际执行脚本，只验证渲染集成点。
        """
        from src.core.workflow_executor import WorkflowExecutor

        executor = WorkflowExecutor("test_wf")
        executor.context = {"greeting": "World"}
        executor.uv_manager = MagicMock()
        executor.uv_manager.get_workflow_dir.return_value = Path(".")
        executor.config_manager = MagicMock()
        executor.config_manager.get_node_timeout_seconds.return_value = 30

        # 添加一个带 {% %} 表达式的节点
        from src.core.node_base import NodeBase
        node = NodeBase.from_dict({
            "node_id": "n1",
            "node_type": "variable_assign",
            "config": {"variable_name": "out", "value": "{% greeting %}"},
            "inputs": [],
            "outputs": [],
        })
        executor.add_node(node)

        with patch.object(executor, "generate_scripts", return_value=[]), \
             patch.object(executor.uv_manager, "send_command_to_worker") as mock_cmd:

            mock_cmd.return_value = {
                "success": True,
                "data": {"out": "World"},
            }

            # 传入一个非空的 worker_process 来触发 send_command_to_worker 路径
            executor._execute_node_with_details(
                "n1", input_data={"x": 1}, worker_process=MagicMock()
            )

            # 验证 config 中的 "value" 被渲染后传给了 worker
            sent_input = mock_cmd.call_args[0][1]["input_data"]
            self.assertEqual(sent_input["value"], "World")
            self.assertEqual(sent_input["x"], 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
