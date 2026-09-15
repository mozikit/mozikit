import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QWidget

from src.core.trigger_definition_registry import get_trigger_definition
from src.views.node_properties import NodePropertiesWidget
from src.views.workflow_tab_widget import WorkflowTabWidget


def _app():
    existing = QApplication.instance()
    if existing is not None and not isinstance(existing, QApplication):
        pytest.skip("another Qt test owns a QCoreApplication in this process")
    return existing or QApplication([])


def test_trigger_visual_and_properties_update_workflow_model_and_round_trip(tmp_path):
    _app()
    tab = WorkflowTabWidget("Demo")
    tab.executor.triggers = [
        {
            "trigger_id": "save-watch",
            "trigger_type": "folder_watch",
            "enabled": True,
            "config": {"path": "D:/Games/A"},
        }
    ]
    tab.add_trigger_visuals(tab.executor.triggers)

    assert "save-watch" in tab.trigger_items
    assert tab.nodes == {}
    assert tab.executor.nodes == {}

    properties = NodePropertiesWidget()
    class _MainWindowStub:
        class _Tabs:
            def setCurrentIndex(self, index):
                self.index = index

        def __init__(self, node_properties):
            self.node_properties = node_properties
            self._right_dock = QWidget()
            self._right_tab_widget = self._Tabs()
            self._right_dock.hide()

    tab.main_window = _MainWindowStub(properties)
    tab._on_node_selected(tab.trigger_items["save-watch"])
    QTest.qWait(30)
    assert properties.current_object_kind == "trigger"

    definition = get_trigger_definition("folder_watch")
    updates = []
    properties.trigger_properties_updated.connect(lambda *args: updates.append(args))
    properties.load_trigger_properties(
        "save-watch",
        "folder_watch",
        tab.get_trigger("save-watch")["config"],
        definition.config_schema,
        True,
    )
    QTest.qWait(30)
    properties.config_widgets["path"].line_edit.setText("D:/Games/B")
    properties.config_widgets["debounce_ms"].setValue(1000)
    properties.sync_current_config()
    assert updates and updates[-1][1]["path"] == "D:/Games/B"

    tab.update_trigger_config(*updates[-1])
    assert tab.get_trigger("save-watch")["config"]["path"] == "D:/Games/B"
    assert tab.is_modified() is True

    output = tmp_path / "workflow.json"
    tab.executor.save_workflow(str(output))
    loaded = tab.executor.load_workflow(str(output))
    assert loaded.triggers[0]["config"]["path"] == "D:/Games/B"
    assert loaded.nodes == {}
