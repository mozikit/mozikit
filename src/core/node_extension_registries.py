"""
节点扩展注册表

为节点类型提供 3 个扩展点，代替硬编码的 is_playwright 分支判断：
  1. SchemaBuilder  — 动态构建 config_schema
  2. BootstrapHook  — 生成完整的 execute() 函数体
  3. Editor         — 节点属性编辑器对话框
"""
from typing import Callable, Dict, Optional

# ── 类型别名 ──────────────────────────────────────────────

SchemaBuilder = Callable[[list, Optional[dict]], dict]
"""(param_names: list, existing_schema: dict | None) → config_schema dict"""

BootstrapHook = Callable[[dict], str]
"""(config: dict) → 完整的 execute(self, input_data) 函数体字符串"""


# ── 注册表基类 ────────────────────────────────────────────

class _Registry:
    """以 node_type 为键的注册表"""

    def __init__(self):
        self._items: Dict[str, object] = {}

    def register(self, node_type: str, item: object):
        self._items[node_type] = item

    def get(self, node_type: str):
        return self._items.get(node_type)

    def has(self, node_type: str) -> bool:
        return node_type in self._items

    def clear(self):
        """供测试用"""
        self._items.clear()


# ── 三个全局注册表实例 ────────────────────────────────────

schema_builders: _Registry = _Registry()
bootstrap_hooks: _Registry = _Registry()
editors: _Registry = _Registry()


# ── 从 node.json registrations 字段动态加载 ──────────────

def load_registrations_from_json(
    node_type: str,
    registrations: dict,
    module_search_path: str,
) -> None:
    """解析 node.json 中的 registrations 字段并注册

    node.json 中的格式:
        "registrations": {
            "schema_builder": {"module": "utils.py", "callable": "build_playwright_config_schema"},
            "bootstrap_hook": {"module": "utils.py", "callable": "build_playwright_inline_wrapper_source"},
            "editor":        {"module": "dialog.py", "callable": "PlaywrightScriptDialog"}
        }

    Args:
        node_type: 节点类型
        registrations: node.json 中的 registrations 字典
        module_search_path: Python 模块文件所在目录路径
    """
    import importlib.util
    import sys
    from pathlib import Path

    search_path = Path(module_search_path)

    mapping = {
        "schema_builder": schema_builders,
        "bootstrap_hook": bootstrap_hooks,
        "editor": editors,
    }

    for key, registry in mapping.items():
        entry = registrations.get(key)
        if not entry:
            continue

        module_name = entry.get("module", "")
        callable_name = entry.get("callable", "")

        if not module_name or not callable_name:
            continue

        module_path = search_path / module_name
        if not module_path.exists():
            continue

        try:
            spec = importlib.util.spec_from_file_location(
                f"{node_type}.{module_name.replace('.py', '')}",
                str(module_path),
            )
            if spec and spec.loader:
                module = importlib.util.module_from_spec(spec)
                sys.modules[spec.name] = module
                spec.loader.exec_module(module)
                func = getattr(module, callable_name, None)
                if func:
                    registry.register(node_type, func)
        except Exception:
            pass
