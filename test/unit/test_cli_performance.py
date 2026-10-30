"""Measure real CLI operations separately from coverage instrumentation."""
import json
import time

import pytest
from typer.testing import CliRunner

from src.cli import app
from src.core.config_manager import ConfigManager
from src.core.workflow_lifecycle import write_document
from test.unit.test_parity_repairs import isolated

pytestmark=pytest.mark.performance


@pytest.fixture
def large_workflow(isolated,monkeypatch):
    from src.core import node_registry
    monkeypatch.setattr(node_registry,'_registry_instance',None)
    _,source,document=isolated
    document['nodes']=[{'node_id':f'n{i}','node_type':'debug','config':{}} for i in range(100)]
    document['edges']=[]
    write_document(source,document)
    return source


def measured(*args):
    start=time.perf_counter()
    result=CliRunner().invoke(app,list(map(str,args)))
    elapsed=time.perf_counter()-start
    assert result.exit_code==0,(result.output,result.exception)
    return elapsed,result.output


def test_run_100_real_nodes_throughput(large_workflow):
    elapsed,output=measured('run',large_workflow,'--json')
    report=json.loads(output)
    assert report['success'] and report['completed_nodes']==100
    assert len(report['nodes'])==100
    assert elapsed<2.0,f'100-node execution took {elapsed:.2f}s (limit 2.0s)'


def test_json_output_has_bounded_overhead(large_workflow):
    normal,_=measured('run',large_workflow)
    machine,output=measured('run',large_workflow,'--json')
    assert json.loads(output)['success']
    assert abs(machine-normal)<0.5,f'JSON {machine:.3f}s vs normal {normal:.3f}s'


def test_list_500_registered_nodes(isolated,monkeypatch):
    from src.core import node_registry
    from src.core.node_registry import get_registry,NodeDefinition,NodeSource
    monkeypatch.setattr(node_registry,'_registry_instance',None)
    for i in range(500):
        get_registry().register_external_node(NodeDefinition(f'perf_{i}',f'Node_{i}',
            'Performance fixture',NodeSource.OFFICIAL,'performance','',{},version='1.0'))
    elapsed,output=measured('node','list')
    assert 'Node_0' in output and 'Node_499' in output
    assert elapsed<1.0,f'500-node rendering took {elapsed:.2f}s (limit 1.0s)'


def test_100_configuration_commits(isolated):
    start=time.perf_counter()
    for i in range(100):measured('config','set',f'key_{i}',i)
    elapsed=time.perf_counter()-start
    config=ConfigManager().config
    assert all(config[f'key_{i}']==i for i in range(100))
    assert elapsed<3.0,f'100 durable config updates took {elapsed:.2f}s (limit 3.0s)'


def test_list_100_persisted_tasks(isolated):
    tasks=[{'id':f'task-{i:04d}','workflow_name':f'wf_{i}','cron_expression':'0 * * * *',
            'enabled':i%2==0,'last_run':None,'next_run':'2026-10-30 00:00:00'} for i in range(100)]
    ConfigManager().set_scheduled_tasks(tasks)
    elapsed,output=measured('schedule','list')
    assert 'wf_0' in output and 'wf_99' in output
    assert elapsed<1.0,f'100-task rendering took {elapsed:.2f}s (limit 1.0s)'
