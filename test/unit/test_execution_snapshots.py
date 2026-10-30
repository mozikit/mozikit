import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli import app
from src.core.node_base import NodeBase
from src.core.workflow_executor import WorkflowExecutor
from src.core.execution_snapshots import ExecutionSnapshots, canonical
from test.unit.test_parity_repairs import isolated


@pytest.fixture
def executed(isolated, monkeypatch):
    executor = WorkflowExecutor('demo')
    executor.workflow_id = 'stable'
    for node_id in ['a', 'b', 'c', 'sibling']:
        executor.add_node(NodeBase.from_dict({'node_id': node_id, 'node_type': 'debug', 'config': {}}))
    for left, right in [('a', 'b'), ('b', 'c'), ('a', 'sibling')]:
        executor.add_edge(left, 'output', right, 'input')
    calls = []
    monkeypatch.setattr(executor, 'generate_scripts', lambda *args: [])
    monkeypatch.setattr(executor, '_check_safety_warning', lambda *args: '')
    def backend(node_id, data, *args):
        calls.append(node_id)
        output = {'output': {'text': 'x' * 2000, 'values': [False, 3, '30']}}
        return output, {'node_id': node_id, 'node_type': 'debug', 'success': True,
                        'duration_ms': 1, 'stdout': '', 'stderr': '', 'error': '', 'input': data, 'output': output}
    monkeypatch.setattr(executor, '_execute_node_with_details', backend)
    report = executor.execute(initial_data={'seed': True}, return_report=True)
    assert report['success'], report
    assert 'snapshot_unavailable' not in report, report
    return executor, report, calls


def test_reuse_upstream_keeps_lossless_values_and_reruns_target(executed):
    executor, report, calls = executed
    required = ExecutionSnapshots().restore(executor, report['run_id'], 'c', {'seed': True})
    assert required == {'a', 'b'}
    assert executor.node_results['b']['output']['output']['text'] == 'x' * 2000
    new = executor.execute(initial_data={'seed': True}, return_report=True, skip_successful_nodes=True,
                           included_node_ids={'a', 'b', 'c'})
    assert calls.count('a') == 1 and calls.count('b') == 1 and calls.count('c') == 2
    assert calls.count('sibling') == 1
    assert [n['node_id'] for n in new['nodes'] if n.get('reused')] == ['a', 'b']
    assert new['run_id'] != report['run_id']


@pytest.mark.parametrize('change', ['identity', 'graph', 'input', 'config', 'source', 'version', 'environment', 'credential'])
def test_changed_upstream_snapshot_rejected_before_mutation(executed, change):
    executor, report, calls = executed
    initial = {'seed': True}
    if change == 'identity':
        executor.workflow_id = 'other'
    elif change == 'graph':
        executor.edges.pop()
    elif change == 'input':
        initial['seed'] = False
    elif change == 'config':
        executor.nodes['a'].config['new'] = 4
    elif change == 'source':
        executor.nodes['a'].source_code = '# changed'
    elif change == 'version':
        executor.nodes['a'].version = '2.0.0'
    elif change == 'credential':
        executor.nodes['a'].config['value'] = '{{credential.demo}}'
    else:
        directory = executor.uv_manager.get_venv_path('demo') / 'lib' / 'example.dist-info'
        directory.mkdir(parents=True)
        (directory / 'METADATA').write_text('Version: 2.0')
    previous = executor.node_results
    with pytest.raises(ValueError):
        ExecutionSnapshots().restore(executor, report['run_id'], 'c', initial)
    assert executor.node_results is previous and len(calls) == 4


def test_target_configuration_may_change(executed):
    executor, report, _ = executed
    executor.nodes['c'].config['new'] = 1
    assert ExecutionSnapshots().restore(executor, report['run_id'], 'c', {'seed': True}) == {'a', 'b'}


@pytest.mark.parametrize('value', [set([1]), (1, 2), {1: 'bad'}, float('nan')])
def test_lossy_or_non_json_output_is_refused(value):
    with pytest.raises((ValueError, TypeError)):
        canonical(value)


@pytest.mark.parametrize('run_id', ['../bad', '/absolute', 'bad\\path', '', '..'])
def test_invalid_snapshot_id_is_refused(isolated, run_id):
    with pytest.raises(ValueError):
        ExecutionSnapshots()._path(run_id)


def test_failed_or_credential_run_does_not_make_snapshot(executed):
    executor, report, _ = executed
    store = ExecutionSnapshots()
    report['run_id'] = 'failed'
    report['success'] = False
    store.save(executor, report)
    assert not store._path('failed').exists()
    report.update(run_id='sensitive', success=True)
    executor.nodes['a'].config['api_key'] = 'SAMPLE-SECRET'
    store.save(executor, report)
    assert not store._path('sensitive').exists()
    assert 'SAMPLE-SECRET' not in report.get('snapshot_unavailable', '')


def test_missing_artifact_rejects_reuse(executed, tmp_path):
    executor, report, _ = executed
    artifact = tmp_path / 'artifact.txt'
    artifact.write_text('artifact')
    executor.node_results['a']['output']['artifacts'] = {'file': str(artifact)}
    store = ExecutionSnapshots()
    store.save(executor, report)
    artifact.unlink()
    with pytest.raises(ValueError, match='产物'):
        store.restore(executor, report['run_id'], 'c', {'seed': True})


def test_old_display_report_is_not_a_snapshot(executed):
    executor, _, _ = executed
    with pytest.raises(ValueError, match='不存在'):
        ExecutionSnapshots().restore(executor, 'old-display-only', 'c')


def test_snapshot_is_current_user_private(executed):
    import os
    executor, report, _ = executed
    if os.name != 'nt':
        path = ExecutionSnapshots()._path(report['run_id'])
        assert path.stat().st_mode & 0o777 == 0o600
        assert path.parent.stat().st_mode & 0o777 == 0o700


def test_cli_requires_target_for_explicit_reuse(isolated):
    _, source, _ = isolated
    result = CliRunner().invoke(app, ['run', str(source), '--reuse-run', 'old', '--json'])
    assert result.exit_code == 1
    assert '--node' in json.loads(result.output)['error']


@pytest.mark.parametrize('replacement',[[],None,{'signatures':[]}, {'reports':{}}, {'artifacts':[{}]}])
def test_malformed_snapshot_is_rejected_without_touching_results(executed,replacement):
    executor,report,calls=executed
    snapshots=ExecutionSnapshots()
    path=snapshots._path(report['run_id'])
    if isinstance(replacement,dict):
        data=json.loads(path.read_text());data.update(replacement)
    else:data=replacement
    path.write_text(json.dumps(data))
    before=executor.node_results
    with pytest.raises(ValueError,match='快照|输出'):
        snapshots.restore(executor,report['run_id'],'c',{'seed':True})
    assert executor.node_results is before and len(calls)==4
