"""GUI operations must keep using a configured workspace outside the launch CWD."""
from pathlib import Path

import pytest

from src.core.workflow_lifecycle import read_document,write_document
from test.unit.test_parity_repairs import isolated

pytestmark=pytest.mark.qt


def test_gui_save_rename_and_delete_share_the_cli_workspace(isolated,tmp_path,monkeypatch,qt_application_session):
    from PySide6.QtWidgets import QMessageBox
    from src.main_window import MainWindow
    from src.core import node_registry
    monkeypatch.setattr(node_registry,'_registry_instance',None)
    _,_,document=isolated
    workspace=tmp_path/'custom workspace'
    source=workspace/'demo'/'workflow.json'
    write_document(source,document)
    (source.parent/'asset.txt').write_bytes(b'original asset')
    monkeypatch.setenv('MOZIKIT_WORKSPACE',str(workspace))
    for method in ['warning','information','critical']:
        monkeypatch.setattr(QMessageBox,method,lambda *a,**k:QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QMessageBox,'question',lambda *a,**k:QMessageBox.StandardButton.Yes)
    window=MainWindow()
    overview=window.tabs.widget(0)
    overview._on_open_workflow('demo',str(source))
    window.show()
    qt_application_session.processEvents()
    widget=window.tabs.currentWidget()
    widget._save_workflow_sync()
    assert Path(widget.workflow_path)==source
    assert read_document(source)['workflow_id']==document['workflow_id']
    widget.rename_workflow()
    widget.name_edit.setText('renamed')
    widget.name_edit.editingFinished.emit()
    widget._save_workflow_sync()
    renamed=workspace/'renamed'/'workflow.json'
    assert renamed.is_file() and not source.exists()
    assert (renamed.parent/'asset.txt').read_bytes()==b'original asset'
    assert read_document(renamed)['workflow_id']==document['workflow_id']
    assert read_document(renamed)['environment_relocated'] is True
    assert not (tmp_path/'workflows'/'renamed').exists()
    overview._on_delete_workflow('renamed')
    assert not renamed.parent.exists()
    widget._is_modified=False
    window.hide();window.deleteLater()
