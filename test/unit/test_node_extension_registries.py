"""测试节点扩展注册表"""
import unittest
from pathlib import Path

from src.core.node_extension_registries import (
    schema_builders,
    bootstrap_hooks,
    editors,
    load_registrations_from_json,
)


try:
    from PySide6 import QtCore
    _HAS_PYSIDE = True
except ImportError:
    _HAS_PYSIDE = False


class TestExtensionRegistries(unittest.TestCase):
    # 注意：不在此清空注册表，避免影响依赖 pre-registered 扩展点的测试。
    # 需要清空注册表的测试应自行调用 clear()。

    def test_register_and_get(self):
        """注册和获取正常工作"""
        fn = lambda x: x
        schema_builders.register("test_node", fn)
        self.assertIs(schema_builders.get("test_node"), fn)
        self.assertTrue(schema_builders.has("test_node"))
        self.assertFalse(schema_builders.has("nonexistent"))

    def test_multiple_registries_independent(self):
        """三个注册表互不干扰"""
        schema_builders.register("node_a", lambda: "schema")
        bootstrap_hooks.register("node_b", lambda: "hook")
        editors.register("node_c", str)

        self.assertTrue(schema_builders.has("node_a"))
        self.assertFalse(schema_builders.has("node_b"))
        self.assertFalse(bootstrap_hooks.has("node_a"))
        self.assertTrue(bootstrap_hooks.has("node_b"))
        self.assertTrue(editors.has("node_c"))

    def test_overwrite_registration(self):
        """重复注册覆盖旧值"""
        old = lambda: 1
        new = lambda: 2
        bootstrap_hooks.register("x", old)
        bootstrap_hooks.register("x", new)
        self.assertIs(bootstrap_hooks.get("x"), new)

    def test_get_nonexistent_returns_none(self):
        """获取未注册的类型返回 None"""
        import uuid
        self.assertIsNone(schema_builders.get(str(uuid.uuid4())))

    def test_clear_resets_all(self):
        """clear 清空所有注册"""
        schema_builders.register("a", lambda: 0)
        schema_builders.register("b", lambda: 0)
        schema_builders.clear()
        self.assertFalse(schema_builders.has("a"))
        self.assertFalse(schema_builders.has("b"))

    def test_load_registrations_from_json_no_file(self):
        """registrations 指向不存在的模块文件时静默忽略"""
        import uuid
        key = str(uuid.uuid4())
        registrations = {
            "schema_builder": {"module": "nonexistent.py", "callable": "func"},
        }
        load_registrations_from_json(key, registrations, "/tmp")
        self.assertFalse(schema_builders.has(key))

    def test_load_registrations_from_json_no_callable(self):
        """registrations 缺少 callable 字段时静默忽略"""
        import uuid
        key = str(uuid.uuid4())
        registrations = {
            "bootstrap_hook": {"module": "nonexistent.py"},
        }
        load_registrations_from_json(key, registrations, "/tmp")
        self.assertFalse(bootstrap_hooks.has(key))








class TestPlaywrightPreRegistered(unittest.TestCase):
    """验证 playwright 扩展点功能正常（不从缓存假设，每次 setUp 自行注册）"""

    def setUp(self):
        from src.core.playwright_node_utils import (
            build_playwright_config_schema,
            _pw_bootstrap_hook,
        )
        schema_builders.register("playwright_script", build_playwright_config_schema)
        bootstrap_hooks.register("playwright_script", _pw_bootstrap_hook)
        try:
            from PySide6 import QtCore
            from src.dialogs.playwright_script_dialog import PlaywrightScriptDialog
            editors.register("playwright_script", PlaywrightScriptDialog)
        except ImportError:
            pass

    def test_schema_builder_registered(self):
        self.assertTrue(schema_builders.has("playwright_script"))
        schema = schema_builders.get("playwright_script")(["url", "limit"])
        self.assertIn("url", schema)
        self.assertIn("playwright_auto_download", schema)

    def test_bootstrap_hook_registered(self):
        self.assertTrue(bootstrap_hooks.has("playwright_script"))
        hook = bootstrap_hooks.get("playwright_script")
        execute_str = hook({
            "script_source": "page.goto('{{url}}')",
            "url": "https://example.com",
        })
        self.assertIn("def execute(self, input_data):", execute_str)
        self.assertIn("LF_HEADLESS", execute_str)
        self.assertIn("LF_AUTO_DOWNLOAD", execute_str)


class TestNodeBaseUsesBootstrapHook(unittest.TestCase):
    """验证 node_base.py 使用 BootstrapHook 而非硬编码"""

    def test_custom_node_uses_hook_when_registered(self):
        """CustomNode._get_script_template 在有 hook 时调用 hook"""
        bootstrap_hooks.clear()
        schema_builders.clear()

        # 注册一个测试 hook
        def test_hook(config):
            return "def execute(self, input_data):\n    return {**input_data, 'from_hook': True}\n"

        bootstrap_hooks.register("test_hook_node", test_hook)

        from src.core.node_base import CustomNode

        node = CustomNode("n1", "test_hook_node", {"key": "val"})
        node.source_code = "def execute(self, input_data):\n    return {**input_data, 'from_source': True}\n"
        template = node._get_script_template()

        self.assertIn("from_hook", template)
        self.assertNotIn("from_source", template)
        self.assertIn("def execute(self, input_data):", template)
        self.assertIn("NODE_CONFIG", template)
        self.assertIn("###JSON_OUTPUT###", template)

    def test_custom_node_falls_back_to_source_code(self):
        """无 hook 时回退到 self.source_code"""
        bootstrap_hooks.clear()
        schema_builders.clear()

        from src.core.node_base import CustomNode

        node = CustomNode("n1", "plain_node", {"key": "val"})
        node.source_code = "def execute(self, input_data):\n    return {**input_data, 'plain': True}\n"
        template = node._get_script_template()

        self.assertIn("plain", template)
        self.assertIn("NODE_CONFIG", template)
        self.assertIn("###JSON_OUTPUT###", template)


class TestNodeRegistryUsesSchemaBuilder(unittest.TestCase):
    """验证 node_registry.py 使用 SchemaBuilder 而非硬编码"""

    def test_schema_builder_replaces_config_schema(self):
        """加载节点时如果注册了 SchemaBuilder，config_schema 被替换"""
        schema_builders.clear()

        # 注册一个 schema builder
        def test_sb(param_names, existing=None):
            return {"dynamic_field": {"type": "string", "label": "动态字段"}}

        schema_builders.register("test_sb_node", test_sb)

        from src.core.node_registry import NodeRegistry

        registry = NodeRegistry()
        # 手动模拟 _apply_schema_builder
        static_schema = {"static_field": {"type": "string"}}
        result = registry._apply_schema_builder("test_sb_node", static_schema)
        self.assertIn("dynamic_field", result)
        self.assertNotIn("static_field", result)

    def test_no_schema_builder_keeps_static(self):
        """无 SchemaBuilder 时保留静态 config_schema"""
        schema_builders.clear()

        from src.core.node_registry import NodeRegistry

        registry = NodeRegistry()
        static_schema = {"field1": {"type": "int"}}
        result = registry._apply_schema_builder("nonexistent", static_schema)
        self.assertEqual(result, static_schema)


if __name__ == "__main__":
    unittest.main()
