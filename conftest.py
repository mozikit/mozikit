"""
pytest 根配置 — 自动跳过依赖 PySide6 的测试文件。
"""
import pytest


def pytest_configure(config):
    """注册自定义标记，检测 PySide6 可用性。"""
    config.addinivalue_line(
        "markers",
        "qt: 标记为依赖 PySide6/Qt 的测试（无 PySide6 时自动跳过）",
    )
    try:
        import PySide6  # noqa: F401
        config._pyside6_available = True
    except ImportError:
        config._pyside6_available = False


def pytest_collection_modifyitems(config, items):
    """根据 PySide6 可用性跳过 Qt 标记的测试。"""
    if getattr(config, "_pyside6_available", False):
        return
    for item in items:
        if item.get_closest_marker("qt"):
            item.add_marker(
                pytest.mark.skip(reason="需要 PySide6（当前环境未安装）")
            )
