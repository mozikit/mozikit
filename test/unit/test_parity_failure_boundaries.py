"""Failure and concurrency regressions must preserve user-owned state."""
from copy import deepcopy
import json
from pathlib import Path
from threading import Barrier,Thread

import pytest

from src.core.config_manager import ConfigManager
from src.core.workflow_lifecycle import WorkflowLifecycle,read_document,write_document
from test.unit.test_parity_repairs import isolated


@pytest.mark.parametrize('change',[
    {'workflow_name':None},{'nodes':{}},{'nodes':[{'node_id':'a','node_type':2}]},
    {'nodes':[{'node_id':'a','node_type':'debug'},{'node_id':'a','node_type':'debug'}]},
    {'edges':[['a']]},{'edges':[['a','missing']]},
])
def test_invalid_workflow_document_rejected_before_copy_or_move(isolated,change):
    workspace,source,document=isolated
    write_document(source,{**document,**change})
    before=source.read_bytes()
    with pytest.raises(ValueError):WorkflowLifecycle().rename(source,'new')
    assert source.read_bytes()==before
    assert not (workspace/'new').exists()


def test_committed_delete_cleanup_can_retry_without_blocking_other_work(isolated,monkeypatch):
    workspace,source,document=isolated
    lifecycle=WorkflowLifecycle()
    import src.core.workflow_lifecycle as module
    original=module.shutil.rmtree
    def locked(path,*args,**kwargs):
        if Path(path).name.startswith('.deleted-'):raise PermissionError('scanner still owns handle')
        return original(path,*args,**kwargs)
    monkeypatch.setattr(module.shutil,'rmtree',locked)
    lifecycle.delete(source)
    assert not source.exists()
    journals=list((workspace/'.transactions').glob('*.json'))
    assert len(journals)==1 and json.loads(journals[0].read_text())['phase']=='committed'
    created=lifecycle.create('other')
    assert created.is_file() and journals[0].is_file()
    monkeypatch.setattr(module.shutil,'rmtree',original)
    lifecycle.recover()
    assert not journals[0].exists() and not list(workspace.glob('.deleted-*'))


def test_rename_legacy_workflow_assigns_stable_old_path_identity(isolated):
    _,source,document=isolated
    document.pop('workflow_id');write_document(source,document)
    target=WorkflowLifecycle().rename(source,'renamed')
    assert read_document(target)['workflow_id']==str(source.resolve())


def test_shared_manager_thread_updates_keep_history_and_task_changes(isolated):
    manager=ConfigManager()
    manager.add_scheduled_task({'id':'task','enabled':True,'next_run':0})
    barrier=Barrier(2);errors=[]
    def history():
        try:
            barrier.wait()
            for i in range(25):manager.add_execution_record({'id':'run-'+str(i),'status':'success'})
        except Exception as exc:errors.append(exc)
    def schedule():
        try:
            barrier.wait()
            for i in range(25):manager.update_scheduled_task('task',{'next_run':i+1})
        except Exception as exc:errors.append(exc)
    threads=[Thread(target=history),Thread(target=schedule)]
    for thread in threads:thread.start()
    for thread in threads:thread.join(10)
    assert not any(thread.is_alive() for thread in threads) and not errors
    fresh=ConfigManager()
    assert fresh.get_scheduled_task('task')['next_run']==25
    assert {row['id'] for row in fresh.get_execution_history()}=={'run-'+str(i) for i in range(25)}


@pytest.mark.parametrize('missing',['node.py','script.py'])
def test_github_incomplete_update_keeps_installed_source_and_current_version(isolated,monkeypatch,tmp_path,missing):
    from src.core.providers.github_provider import GitHubNodeProvider
    from src.core import node_registry
    monkeypatch.setattr(node_registry,'_registry_instance',None)
    provider=GitHubNodeProvider(tmp_path/'data')
    info={'node_type':'download-test','name':'Download test','version':'1.0.0','entry_file':'node.py',
          'metadata':{'node_kind':'playwright_script','script_file':'script.py'}}
    content={'node.py':'def execute(self, input_data):\n    return input_data\n','script.py':'print("original")'}
    monkeypatch.setattr(provider,'_get_repo_file_json',lambda *a:(200,deepcopy(info)))
    monkeypatch.setattr(provider,'_download_file',lambda _o,_r,path:content.get(path))
    old=provider._download_node_from_path('owner','repo','','https://github.com/owner/repo')
    assert old is not None
    version=provider.version_manager.get_version_dir('download-test','1.0.0')
    snapshot={p.name:p.read_bytes() for p in version.iterdir()}
    manifest=provider.version_manager.get_manifest_path('download-test').read_bytes()
    content[missing]=None
    # An in-place refresh and a new-version update both preserve the working install.
    for requested in ['1.0.0','2.0.0']:
        assert provider._download_node_from_path('owner','repo','','https://github.com/owner/repo',requested) is None
        assert {p.name:p.read_bytes() for p in version.iterdir()}==snapshot
        assert provider.version_manager.get_manifest_path('download-test').read_bytes()==manifest
        assert provider.version_manager.resolve_current_version('download-test')=='1.0.0'
        assert node_registry.get_registry().get_node('download-test').source_code==old.source_code
    assert not provider.version_manager.get_version_dir('download-test','2.0.0').exists()
    assert not list(version.parent.glob('.download-*'))


@pytest.mark.parametrize('version',['../outside','..','C:\\outside','', '1.0 '])
def test_generated_version_cannot_escape_node_directory(isolated,tmp_path,version):
    from src.core.custom_node_manager import CustomNodeManager
    manager=CustomNodeManager(tmp_path/'node-data')
    before=list(manager.custom_nodes_dir.rglob('node.json'))
    with pytest.raises(ValueError):
        manager.create_generated_node('bad-version','description','def execute(self,input_data):\n    return {}\n',version=version)
    assert list(manager.custom_nodes_dir.rglob('node.json'))==before
    assert not (tmp_path/'outside').exists()
