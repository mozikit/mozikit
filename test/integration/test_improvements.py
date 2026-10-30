"""Real model and GUI assertions replace the old print-only manual checklist."""
import json
from pathlib import Path
import pytest


def test_workflow_json_format(tmp_path, monkeypatch):
    from src.core.workflow_executor import WorkflowExecutor
    from src.core.node_base import NodeBase
    monkeypatch.setenv('MOZIKIT_WORKSPACE', str(tmp_path/'workspace'))
    executor=WorkflowExecutor('demo')
    executor.add_node(NodeBase.from_dict({'node_id':'a','node_type':'debug','config':{}}))
    path=tmp_path/'workflow.json'
    executor.save_workflow(str(path), node_positions={'a':{'x':12,'y':24}})
    document=json.loads(path.read_text())
    assert document['workflow_name']=='demo'
    assert document['nodes'][0]['position']=={'x':12,'y':24}


@pytest.mark.qt
def test_node_browser_drag(qt_application_session):
    from src.views.node_browser import NodeBrowserWidget
    widget=NodeBrowserWidget()
    try:
        assert widget.node_list.dragEnabled()
    finally:
        widget.close()
        widget.deleteLater()


@pytest.mark.qt
def test_node_deletion(qt_application_session):
    from src.views.workflow_tab_widget import WorkflowTabWidget
    widget=WorkflowTabWidget('demo')
    try:
        assert len(widget.nodes)==0
        # The canvas creates a real graphics item and emits its model signal.
        from PySide6.QtGui import QAction
        from PySide6.QtCore import QPointF
        action=QAction('debug', widget)
        action.setData(('debug', 'Debug'))
        widget.canvas._add_node_from_action(action, QPointF(12,24))
        assert len(widget.nodes)==1
        node_id=next(iter(widget.nodes))
        widget.nodes[node_id].delete_node()
        assert node_id not in widget.nodes
    finally:
        widget.close()
        widget.deleteLater()


@pytest.mark.qt
def test_properties_panel(qt_application_session):
    from src.views.node_properties import NodePropertiesWidget
    panel=NodePropertiesWidget()
    try:
        panel.load_node_properties('a','debug',{'max_length':500})
        panel._do_load_node_properties()
        assert panel.current_node_id=='a'
        assert panel.current_config['max_length']==500
    finally:
        panel.close()
        panel.deleteLater()


def test_workflow_list(tmp_path):
    from src.core.workflow_scanner import WorkflowScanner
    file=tmp_path/'demo'/'workflow.json'
    file.parent.mkdir()
    file.write_text(json.dumps({'workflow_name':'demo','nodes':[{'node_id':'a','node_type':'debug'}],'edges':[]}))
    scanner=WorkflowScanner(str(tmp_path))
    scanner.scan_all_workflows()
    usage=scanner.get_workflows_using_node('debug')
    assert len(usage)==1 and usage[0].node_ids==['a']
