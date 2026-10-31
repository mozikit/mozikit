"""Offscreen GUI coverage for the ACP node's ports and schema-driven form."""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")
from PySide6.QtCore import Qt, QPointF
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QApplication, QGraphicsScene

from src.core.node_base import CustomNode, NodeBase
from src.core.node_registry import NodeRegistry
from src.views import node_browser, node_properties
from src.views.workflow_canvas import WorkflowCanvas


def test_acp_node_is_available_and_gui_config_roundtrips(tmp_path, monkeypatch):
    app = QApplication.instance()
    if app is not None and not isinstance(app, QApplication):
        pytest.skip("another test owns a QCoreApplication")
    app = app or QApplication([])
    monkeypatch.chdir(tmp_path)
    registry = NodeRegistry()
    monkeypatch.setattr("src.core.node_registry.get_registry", lambda: registry)
    for module in (node_browser, node_properties):
        monkeypatch.setattr(module, "get_registry", lambda: registry)

    browser = node_browser.NodeBrowserWidget()
    properties = node_properties.NodePropertiesWidget()
    scene = QGraphicsScene()
    canvas = WorkflowCanvas(scene)
    try:
        created = []
        canvas.node_added.connect(created.append)
        action = QAction("ACP Agent", canvas)
        action.setData(("acp_agent", "ACP Agent"))
        canvas._add_node_from_action(action, QPointF(0, 0))
        item = created[0]
        available = [
            browser.node_list.item(i).data(Qt.UserRole)
            for i in range(browser.node_list.count())
        ]
        assert any(node["type_str"] == "acp_agent" for node in available)
        assert {port.port_name for port in item.input_ports} == {"prompt", "input"}
        assert {port.port_name for port in item.output_ports} == {
            "text",
            "session_id",
            "stop_reason",
            "updates",
        }
        properties.load_node_properties("agent", "acp_agent", {})
        properties._do_load_node_properties()
        widgets = properties.config_widgets
        widgets["agent"].setText("my-acp-agent")
        widgets["args"].setPlainText("--acp\nargument with spaces")
        widgets["cwd"].line_edit.setText("artifacts")
        widgets["prompt"].setPlainText("总结 {% input %}\n请保留换行")
        widgets["timeout"].setValue(45)
        config = properties._collect_current_config()
        assert config["args"] == ["--acp", "argument with spaces"]
        assert config["prompt"] == "总结 {% input %}\n请保留换行"
        assert config["cwd"] == "artifacts"
        loaded = NodeBase.from_dict(CustomNode("agent", "acp_agent", config).to_dict())
        assert loaded.config == config
        assert loaded.config["timeout"] == 45
    finally:
        browser.close()
        properties.close()
        canvas.close()
        browser.deleteLater()
        properties.deleteLater()
        canvas.deleteLater()
        app.processEvents()
