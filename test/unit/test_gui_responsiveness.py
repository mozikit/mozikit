"""Qt interaction regressions; all registries/configuration are isolated."""
import os
from unittest.mock import Mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QApplication, QGraphicsScene, QTabWidget, QTableWidget, QVBoxLayout, QWidget,
)

from src.views import node_browser, workflow_canvas
from src.views.node_graphics import NodeGraphicsItem
from src.views.overview_widget import OverviewWidget


@pytest.fixture
def app():
    existing = QApplication.instance()
    if existing is not None and not isinstance(existing, QApplication):
        pytest.skip("another test owns a QCoreApplication")
    return existing or QApplication([])


@pytest.fixture
def browser(app, monkeypatch):
    nodes = [
        dict(name="Alpha", description="first", category="Text",
             source=node_browser.NodeSource.OFFICIAL),
        dict(name="Beta", description="second", category="Files",
             source=node_browser.NodeSource.GITHUB, repo_url="https://github.com/test/tools"),
    ]
    registry = Mock()
    registry.get_all_nodes.return_value = nodes
    monkeypatch.setattr(node_browser, "get_registry", lambda: registry)
    widget = node_browser.NodeBrowserWidget()
    yield widget
    widget.close()
    widget.deleteLater()


def test_search_reuses_items_and_preserves_matching_selection(browser):
    first, second = (browser.node_list.item(i) for i in range(2))
    browser.node_list.setCurrentItem(second)
    for query in ("b", "be", " BETA ", "@tools", ""):
        browser.search_input.setText(query)
        assert browser.node_list.item(0) is first
        assert browser.node_list.item(1) is second
        assert browser.node_list.currentItem() is second
        assert not second.isHidden()
    browser.search_input.setText("missing")
    assert first.isHidden() and second.isHidden()
    browser.search_input.clear()
    assert not first.isHidden() and not second.isHidden()


def test_reload_keeps_source_and_search_filters(browser):
    browser.source_filter.setCurrentIndex(2)
    browser.search_input.setText("@tools")
    browser._load_nodes()
    assert browser.node_list.item(0).isHidden()
    assert not browser.node_list.item(1).isHidden()
    browser.search_input.setText("Alpha")
    assert all(browser.node_list.item(i).isHidden() for i in range(2))
    browser.source_filter.setCurrentIndex(0)
    assert not browser.node_list.item(0).isHidden()


@pytest.fixture
def canvas(app, monkeypatch):
    monkeypatch.setattr(workflow_canvas, "ConfigManager", Mock)
    scene = QGraphicsScene()
    view = workflow_canvas.WorkflowCanvas(scene)
    yield view
    view.close()
    view.deleteLater()


def wheel(view, angle=0, pixel=0):
    event = QWheelEvent(
        QPointF(100, 100), QPointF(100, 100), QPoint(0, pixel), QPoint(0, angle),
        Qt.NoButton, Qt.NoModifier, Qt.NoScrollPhase, False,
    )
    view.wheelEvent(event)


def test_idle_canvas_has_no_active_polling_timer(canvas):
    assert not any(timer.isActive() for timer in canvas.findChildren(QTimer))


def test_zero_wheel_does_not_zoom_or_schedule_save(canvas):
    wheel(canvas)
    assert canvas.transform().m11() == 1
    assert not canvas._zoom_save_timer.isActive()
    assert not canvas._zoom_auto_save_timer.isActive()


def test_small_wheel_deltas_compose_to_one_notch(canvas):
    for _ in range(4):
        wheel(canvas, angle=30)
    assert canvas.transform().m11() == pytest.approx(1.15)
    wheel(canvas, angle=-120)
    assert canvas.transform().m11() == pytest.approx(1)
    wheel(canvas, pixel=10)
    assert 1 < canvas.transform().m11() < 1.15


def test_zoom_clamps_at_limits_without_scheduling_redundant_save(canvas):
    for _ in range(12):
        wheel(canvas, angle=120)
    assert canvas._current_zoom == canvas._max_zoom
    canvas._zoom_save_timer.stop()
    canvas._zoom_auto_save_timer.stop()
    wheel(canvas, angle=120)
    assert not canvas._zoom_save_timer.isActive()
    assert not canvas._zoom_auto_save_timer.isActive()
    for _ in range(40):
        wheel(canvas, angle=-120)
    assert canvas._current_zoom == canvas._min_zoom


def test_node_move_updates_connections_at_new_position(app):
    scene = QGraphicsScene()
    node = NodeGraphicsItem("test", "test")
    scene.addItem(node)
    positions = []
    node._update_connected_connections = lambda: positions.append(node.pos())
    node.setPos(50, 75)
    assert positions == [QPointF(50, 75)]
    app.processEvents()
    assert len(positions) == 1


def test_overview_only_refreshes_visible_page(app):
    # Build a minimal real Qt hierarchy without accessing credentials/history.
    widget = OverviewWidget.__new__(OverviewWidget)
    QWidget.__init__(widget)
    widget._load_scheduled_tasks = Mock()
    widget._load_execution_history = Mock()
    widget.scheduled_table = QTableWidget()
    widget.history_table = QTableWidget()
    tabs = QTabWidget()
    tabs.addTab(QWidget(), "workflows")
    tabs.addTab(widget.scheduled_table, "schedule")
    tabs.addTab(widget.history_table, "history")
    QVBoxLayout(widget).addWidget(tabs)
    tabs.currentChanged.connect(widget._refresh_data)
    widget._refresh_data()
    widget.show()
    app.processEvents()
    widget._load_scheduled_tasks.assert_not_called()
    widget._load_execution_history.assert_not_called()
    tabs.setCurrentIndex(1)
    widget._load_scheduled_tasks.assert_called_once()
    widget._load_execution_history.assert_not_called()
    widget.hide()
    widget._refresh_data()
    widget._load_scheduled_tasks.assert_called_once()
    widget.show()
    widget._load_scheduled_tasks.assert_called_with()
    assert widget._load_scheduled_tasks.call_count == 2
    tabs.setCurrentIndex(2)
    widget._load_execution_history.assert_called_once()
    widget.close()
    widget.deleteLater()
