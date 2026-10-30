"""Regression tests exercise actual files and fresh readers, not mocked managers."""
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock

import pytest
from typer.testing import CliRunner

from src.cli import app
from src.core.config_manager import ConfigManager
from src.core.workflow_lifecycle import WorkflowLifecycle, validate_workflow_name, run_lock, write_document
from src.core.workflow_executor import WorkflowExecutor


@pytest.fixture
def isolated(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('MOZIKIT_APP_DATA_DIR', str(tmp_path / 'data'))
    monkeypatch.delenv('MOZIKIT_CONFIG_PATH', raising=False)
    monkeypatch.setenv('MOZIKIT_WORKSPACE', str(tmp_path / 'workflows'))
    workspace = tmp_path / 'workflows'
    workspace.mkdir()
    source = workspace / 'demo' / 'workflow.json'
    document = {'version': 2, 'workflow_id': 'stable', 'workflow_name': 'demo', 'active': False,
                'nodes': [{'node_id': 'a', 'node_type': 'debug', 'config': {}, 'position': {'x': 12, 'y': 23}, 'extension': {'keep': True}}],
                'edges': [], 'triggers': [], 'canvas_state': {'scale_x': 1.2}, 'extension': {'v': [1, False]}}
    write_document(source, document)
    (source.parent / 'input.csv').write_bytes(b'id,value\n1,42\n')
    return workspace, source, document


def invoke(*args):
    result = CliRunner().invoke(app, list(map(str, args)))
    assert result.exit_code == 0, (result.output, result.exception)
    return result


def test_rename_preserves_files_coordinates_and_references(isolated):
    workspace, source, document = isolated
    mgr = ConfigManager()
    mgr.config = {'scheduled_tasks': [{'id': 'task', 'workflow_name': 'demo', 'workflow_path': str(source), 'enabled': True}],
                  'execution_history': [{'id': 'run', 'workflow_name': 'demo', 'artifact_dir': str(source.parent / 'runs' / 'run')}],
                  'recent_workflows': [{'name': 'demo', 'path': str(source)}]}
    mgr.save_config_sync()
    invoke('workflow', 'rename', source, 'renamed')
    target = workspace / 'renamed'
    actual = json.loads((target / 'workflow.json').read_text())
    assert actual == {**document, 'workflow_name': 'renamed', 'environment_relocated': True}
    assert (target / 'input.csv').read_bytes() == b'id,value\n1,42\n'
    assert not source.parent.exists()
    fresh = ConfigManager().config
    assert fresh['scheduled_tasks'][0]['workflow_path'] == str(target / 'workflow.json')
    assert fresh['execution_history'][0]['workflow_name'] == 'demo'
    assert fresh['execution_history'][0]['artifact_dir'] == str(target / 'runs' / 'run')


@pytest.mark.parametrize('name', ['', ' ', '.', '..', '../outside', 'sub/name', 'sub\\name', 'C:\\outside', 'CON', 'aux.txt', 'bad:name', 'end.'])
def test_invalid_names_rejected_without_creating_directories(isolated, name):
    workspace, _, _ = isolated
    before = set(workspace.iterdir())
    with pytest.raises(ValueError):
        WorkflowLifecycle().create(name)
    assert {p for p in workspace.iterdir() if not p.name.startswith('.')} == before


def test_trim_unicode_name(isolated):
    assert validate_workflow_name('  新流程  ') == '新流程'
    assert WorkflowLifecycle().create('  新流程  ').parent.name == '新流程'


@pytest.mark.parametrize('target', ['text', 'outside', 'root', 'invalid'])
def test_delete_refuses_non_owned_documents(isolated, tmp_path, target):
    workspace, source, doc = isolated
    candidates = {'text': source.parent / 'input.csv', 'outside': tmp_path / 'outside' / 'workflow.json',
                  'root': workspace, 'invalid': workspace / 'broken' / 'workflow.json'}
    write_document(candidates['outside'], doc)
    write_document(candidates['invalid'], {})
    result = CliRunner().invoke(app, ['workflow', 'delete', str(candidates[target])])
    assert result.exit_code == 1
    assert source.exists() and candidates['outside'].exists()


def test_external_symlink_rejected(isolated, tmp_path):
    workspace, _, doc = isolated
    external = tmp_path / 'outside'
    write_document(external / 'workflow.json', doc)
    try:
        (workspace / 'link').symlink_to(external, target_is_directory=True)
    except OSError:
        pytest.skip('directory symlinks require host privileges; junction case runs in Windows CI')
    with pytest.raises(ValueError):
        WorkflowLifecycle().delete(workspace / 'link')
    assert (external / 'workflow.json').is_file()


@pytest.mark.parametrize('operation', ['rename', 'delete'])
def test_active_and_running_workflow_cannot_move(isolated, operation):
    _, source, doc = isolated
    service = WorkflowLifecycle()
    method = getattr(service, operation)
    args = (source, 'new') if operation == 'rename' else (source,)
    doc['active'] = True
    write_document(source, doc)
    with pytest.raises(ValueError, match='停用'):
        method(*args)
    doc['active'] = False
    write_document(source, doc)
    with run_lock('stable'):
        with pytest.raises(ValueError, match='执行'):
            method(*args)
    assert source.is_file()


def test_rename_write_failure_rolls_back(isolated, monkeypatch):
    workspace, source, doc = isolated
    from src.core import workflow_lifecycle as lifecycle
    original = lifecycle.write_document
    def fail(path, data):
        if Path(path) == workspace / 'new' / 'workflow.json':
            raise PermissionError('injected write denial')
        return original(path, data)
    monkeypatch.setattr(lifecycle, 'write_document', fail)
    with pytest.raises(PermissionError):
        WorkflowLifecycle().rename(source, 'new')
    assert json.loads(source.read_text()) == doc
    assert (source.parent / 'input.csv').exists()
    assert not (workspace / 'new').exists()


def test_copy_import_export_keep_layout_and_new_identity(isolated, tmp_path):
    workspace, source, doc = isolated
    (source.parent / '.venv').mkdir()
    invoke('workflow', 'copy', source, 'copied')
    copied = json.loads((workspace / 'copied' / 'workflow.json').read_text())
    assert copied['workflow_id'] != doc['workflow_id'] and copied['active'] is False
    assert copied['nodes'] == doc['nodes']
    assert not (workspace / 'copied' / '.venv').exists()
    assert (workspace / 'copied' / 'input.csv').read_bytes() == (source.parent / 'input.csv').read_bytes()
    output = tmp_path / 'exported.json'
    invoke('workflow', 'export', source, '--output', output)
    invoke('workflow', 'import', output, '--name', 'imported')
    imported = json.loads((workspace / 'imported' / 'workflow.json').read_text())
    assert imported['nodes'][0]['position'] == doc['nodes'][0]['position']
    assert imported['extension'] == doc['extension']
    assert imported['workflow_id'] not in {doc['workflow_id'], copied['workflow_id']}


def test_delete_disables_only_own_tasks(isolated):
    _, source, _ = isolated
    mgr = ConfigManager()
    mgr.config['scheduled_tasks'] = [{'id': 'mine', 'workflow_path': str(source), 'enabled': True},
                                     {'id': 'other', 'workflow_path': '/other/workflow.json', 'enabled': True}]
    mgr.save_config_sync()
    invoke('workflow', 'delete', source)
    tasks = ConfigManager().get_scheduled_tasks()
    assert [t['enabled'] for t in tasks] == [False, True]


def test_node_edits_preserve_extension_and_positions(isolated):
    _, source, original = isolated
    invoke('workflow', 'update-node', source, 'a', 'enabled=false', 'count=30')
    actual = json.loads(source.read_text())
    assert actual['extension'] == original['extension']
    assert actual['nodes'][0]['extension'] == original['nodes'][0]['extension']
    assert actual['nodes'][0]['position'] == original['nodes'][0]['position']
    assert actual['nodes'][0]['config'] == {'enabled': False, 'count': 30}


def test_stale_configuration_merges_nested_changes_and_deletions(isolated):
    first, second = ConfigManager(), ConfigManager()
    first.config['options'] = {'a': 1}
    first.save_config()
    second.config['options'] = {'b': 2}
    second.save_config()
    assert ConfigManager().config['options'] == {'a': 1, 'b': 2}
    first = ConfigManager()
    del first.config['options']['a']
    first.save_config()
    assert ConfigManager().config['options'] == {'b': 2}


def test_concurrent_processes_preserve_committed_history(isolated, tmp_path):
    root = str(Path(__file__).resolve().parents[2])
    script = ('import sys;sys.path.insert(0,sys.argv[1]);from src.core.config_manager import ConfigManager;'
              'm=ConfigManager();m.add_execution_record({"id":sys.argv[2],"status":"success"})')
    processes = [subprocess.Popen([sys.executable, '-c', script, root, str(index)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) for index in range(6)]
    assert all(process.wait(timeout=20) == 0 for process in processes)
    assert {r['id'] for r in ConfigManager().get_execution_history()} == {str(i) for i in range(6)}


def test_atomic_replace_retries_and_failure_retains_old_file(isolated, tmp_path, monkeypatch):
    from src.core import _file_utils as files
    target = tmp_path / 'atomic.json'
    target.write_text('old')
    original = files.os.replace
    attempts = []
    def busy(source, destination):
        attempts.append(1)
        if len(attempts) < 3:
            raise PermissionError('busy')
        return original(source, destination)
    monkeypatch.setattr(files.os, 'replace', busy)
    monkeypatch.setattr(files.time, 'sleep', lambda duration: None)
    files.atomic_write(target, 'new')
    assert target.read_text() == 'new' and len(attempts) == 3
    monkeypatch.setattr(files.os, 'replace', lambda *a: (_ for _ in ()).throw(PermissionError('denied')))
    with pytest.raises(PermissionError):
        files.atomic_write(target, 'broken')
    assert target.read_text() == 'new'
    assert not list(tmp_path.glob('*.tmp'))


def test_schedule_change_preserves_identity_and_failed_update_is_atomic(isolated):
    workspace, source, doc = isolated
    write_document(workspace / 'beta' / 'workflow.json', {**doc, 'workflow_name': 'beta', 'workflow_id': 'beta'})
    from src.core.headless_scheduler import HeadlessScheduler
    scheduler = HeadlessScheduler()
    task_id = scheduler.add_task('demo', str(source))
    invoke('schedule', 'update', task_id, '--workflow', workspace / 'beta' / 'workflow.json')
    task = ConfigManager().get_scheduled_task(task_id)
    assert task['workflow_name'] == 'beta' and Path(task['workflow_path']) == workspace / 'beta' / 'workflow.json'
    before = deepcopy(task)
    result = CliRunner().invoke(app, ['schedule', 'update', task_id, '--workflow', str(source), '--cron', 'invalid'])
    assert result.exit_code == 1
    assert ConfigManager().get_scheduled_task(task_id) == before
