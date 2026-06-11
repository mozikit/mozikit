"""
Jinja2 沙箱表达式引擎

在节点执行前，将 config 字符串中的 {% expression %} 渲染为工作流上下文中的值。
使用 {% %} 定界符避免与 {{credential.xxx}} 凭证占位符冲突。
"""

from typing import Any, Dict, List, Tuple, Union

try:
    from jinja2 import BaseLoader, Undefined
    from jinja2.sandbox import SandboxedEnvironment

    class _SilentUndefined(Undefined):
        """缺失引用渲染为空字符串，不抛出异常。"""
        __slots__ = ()

        def _fail_with_undefined_error(self, *args, **kwargs):
            return ""

    _EXPR_ENV = SandboxedEnvironment(
        loader=BaseLoader(),
        variable_start_string="{%",
        variable_end_string="%}",
        block_start_string="<@",
        block_end_string="@>",
        comment_start_string="{##",
        comment_end_string="##}",
        undefined=_SilentUndefined,
        autoescape=False,
    )
    HAS_JINJA2 = True
except ImportError:
    HAS_JINJA2 = False


def render_expressions(value: Any, context: dict) -> Any:
    """递归扫描数据结构，渲染字符串值中的 {% %} 表达式。

    非字符串、不含定界符的值直接透传。
    缺失的引用渲染为空字符串（UndefinedSilent），不会抛出异常。

    Args:
        value: 任意 Python 值（str/dict/list/等）
        context: 工作流上下文（包含所有上游节点的输出）

    Returns:
        渲染后的值，类型与输入一致
    """
    if not HAS_JINJA2:
        return value

    if isinstance(value, str):
        if "{%" in value and "%}" in value:
            template = _EXPR_ENV.from_string(value)
            return template.render(**context)
        return value

    if isinstance(value, dict):
        return {k: render_expressions(v, context) for k, v in value.items()}

    if isinstance(value, (list, tuple)):
        return [render_expressions(item, context) for item in value]

    return value
