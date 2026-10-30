"""Widget lifetime and refresh checks share the session QApplication."""
import pytest

pytestmark=pytest.mark.qt


def test_imports():
    from src.views.overview_widget import OverviewWidget, WorkflowCard
    from src.views.workflow_tab_widget import WorkflowTabWidget
    assert OverviewWidget and WorkflowCard and WorkflowTabWidget


def test_overview_refresh_logic(qt_application_session, tmp_path, monkeypatch):
    from src.views.overview_widget import OverviewWidget
    monkeypatch.chdir(tmp_path)
    widget=OverviewWidget()
    try:
        for _ in range(3):
            widget.refresh_workflows()
            qt_application_session.processEvents()
        assert widget.list_layout.indexOf(widget.empty_label) >= 0
        assert widget.list_layout.count() == 1
    finally:
        widget.close()
        widget.deleteLater()


def test_workflow_tab_save(qt_application_session, tmp_path, monkeypatch):
    from src.views.workflow_tab_widget import WorkflowTabWidget
    monkeypatch.chdir(tmp_path)
    widget=WorkflowTabWidget('保存测试')
    try:
        widget._save_workflow_sync()
        assert (tmp_path/'workflows'/'保存测试'/'workflow.json').is_file()
    finally:
        widget.close()
        widget.deleteLater()
