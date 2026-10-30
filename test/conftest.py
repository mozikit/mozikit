"""
测试共享 fixtures — CliRunner, 临时目录, 配置隔离等。
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest


@pytest.fixture(scope='session', autouse=True)
def qt_application_session(request):
    """Keep one QApplication alive across QCoreApplication and QWidget tests."""
    if not getattr(request.config, '_pyside6_available', False):
        yield None
        return
    os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QCoreApplication, QEvent
    application = QApplication.instance() or QApplication([])
    yield application
    for widget in application.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    application.processEvents()

@pytest.fixture(autouse=True)
def dispose_test_widgets(qt_application_session):
    """Drain deferred widget deletion before the next test processes Qt events."""
    app = qt_application_session
    if app is None:
        yield
        return
    from PySide6.QtCore import QCoreApplication, QEvent
    from shiboken6 import isValid
    existing = set(app.topLevelWidgets())
    yield
    for widget in set(app.topLevelWidgets()) - existing:
        if isValid(widget):
            widget.hide()
            widget.deleteLater()
    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)


# 确保 src/ 可导入
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


@pytest.fixture
def cli_runner():
    """提供 Typer CliRunner 实例。"""
    from typer.testing import CliRunner
    return CliRunner()


@pytest.fixture
def tmp_project_dir():
    """创建临时项目目录，自动清理。"""
    tmp = Path(tempfile.mkdtemp(prefix="mozikit_test_"))
    yield tmp
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def isolated_config(tmp_project_dir):
    """在临时目录中创建隔离的 ConfigManager。"""
    from src.core.config_manager import ConfigManager
    config_file = tmp_project_dir / "config.json"
    mgr = ConfigManager(str(config_file))
    return mgr


@pytest.fixture
def mock_registry():
    """Mock 的节点注册表。"""
    registry = MagicMock()
    registry._user_data_dir = "/tmp/test_user_data"
    return registry
