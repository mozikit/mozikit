"""
src/gui_entry 单元测试 — GUI 入口与打包运行目录逻辑。
不依赖真实 PySide6/Qt 运行时，无 PySide6 环境也可执行。
"""
import os
import sys
import types
from pathlib import Path
from unittest.mock import Mock, patch

import pytest

PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, PROJECT_ROOT)

from src.gui_entry import _prepare_runtime_workdir, run_gui


# ── _prepare_runtime_workdir ──────────────────────────────


def test_workdir_not_frozen_is_noop():
    """非 frozen 环境（源码运行）不应切换工作目录。"""
    with patch("os.chdir") as mock_chdir, patch("pathlib.Path.mkdir") as mock_mkdir:
        _prepare_runtime_workdir()
    mock_chdir.assert_not_called()
    mock_mkdir.assert_not_called()


def test_workdir_frozen_uses_appdata():
    """frozen（打包 EXE）时使用 APPDATA/Mozikit 并切换目录。"""
    with patch.object(sys, "frozen", True, create=True), \
         patch("os.environ", {"APPDATA": "C:/Users/tester/AppData/Roaming"}), \
         patch("pathlib.Path.mkdir") as mock_mkdir, \
         patch("os.chdir") as mock_chdir:
        _prepare_runtime_workdir()

    expected = Path("C:/Users/tester/AppData/Roaming/Mozikit")
    mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
    mock_chdir.assert_called_once_with(expected)


def test_workdir_frozen_falls_back_to_home():
    """frozen 且无 APPDATA 时回退到 ~/AppData/Roaming/Mozikit。"""
    with patch.object(sys, "frozen", True, create=True), \
         patch("os.environ", {}), \
         patch("pathlib.Path.home", return_value=Path("C:/Users/tester")), \
         patch("pathlib.Path.mkdir") as mock_mkdir, \
         patch("os.chdir") as mock_chdir:
        _prepare_runtime_workdir()

    expected = Path("C:/Users/tester/AppData/Roaming/Mozikit")
    mock_mkdir.assert_called_once_with(parents=True, exist_ok=True)
    mock_chdir.assert_called_once_with(expected)


# ── run_gui ──────────────────────────────────────────────


def test_run_gui_without_pyside6_prints_hint_and_exits(capsys):
    """未安装 PySide6 时应输出安装提示并以状态码 1 退出。"""
    with patch.dict("sys.modules", {"PySide6": None, "PySide6.QtWidgets": None}):
        with pytest.raises(SystemExit) as exc_info:
            run_gui()

    assert exc_info.value.code == 1
    err = capsys.readouterr().err
    assert "PySide6" in err
    assert "[gui]" in err


def test_run_gui_starts_application():
    """已安装 PySide6 时按序初始化日志、应用主题并显示主窗口。"""
    fake_qt = types.ModuleType("PySide6.QtWidgets")

    class FakeQApplication:
        instances = []

        def __init__(self, argv):
            self.argv = argv
            FakeQApplication.instances.append(self)

        def exec(self):
            return 42

    fake_qt.QApplication = FakeQApplication

    fake_log = types.ModuleType("src.core.log_manager")
    fake_log.init_logging = Mock()
    fake_theme = types.ModuleType("src.core.theme_manager")
    fake_theme.ThemeManager = Mock()
    fake_runtime = types.ModuleType("src.core.runtime_host")
    runtime_host = Mock()
    fake_runtime.RuntimeHost = Mock(return_value=runtime_host)
    fake_win = types.ModuleType("src.main_window")
    window = Mock()
    fake_win.MainWindow = Mock(return_value=window)

    with patch.dict(
        "sys.modules",
        {
            "PySide6": types.ModuleType("PySide6"),
            "PySide6.QtWidgets": fake_qt,
            "src.core.log_manager": fake_log,
            "src.core.runtime_host": fake_runtime,
            "src.core.theme_manager": fake_theme,
            "src.main_window": fake_win,
        },
    ):
        with patch.object(sys, "exit") as mock_exit:
            run_gui()

    app = FakeQApplication.instances[-1]
    assert app.argv is sys.argv
    fake_log.init_logging.assert_called_once_with()
    fake_theme.ThemeManager.apply_theme.assert_called_once_with(app)
    fake_runtime.RuntimeHost.assert_called_once_with()
    runtime_host.start.assert_called_once_with()
    runtime_host.stop.assert_called_once_with()
    fake_win.MainWindow.assert_called_once_with()
    window.show.assert_called_once_with()
    mock_exit.assert_called_once_with(42)


def test_main_run_gui_delegates_to_gui_entry():
    """main.run_gui 应委托给 src.gui_entry.run_gui。"""
    import main

    with patch("src.gui_entry.run_gui") as mock_run:
        main.run_gui()
    mock_run.assert_called_once_with()
