"""Exercise real CLI state, HTTP API routes and terminal output contracts."""
from copy import deepcopy
import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli import app
from src.core.config_manager import ConfigManager
from src.core.workflow_lifecycle import write_document
from test.unit.test_parity_repairs import isolated


def cmd(*args,code=0,input=None):
    result=CliRunner().invoke(app,list(map(str,args)),input=input)
    assert result.exit_code==code,(result.output,result.exception)
    return result


def test_registration_commands_surface_state_and_source_failures(isolated):
    payload=json.loads(cmd('cli','status','--json').output)
    assert payload['status']=='not registered' and payload['source'] is None
    assert 'not registered' in cmd('cli','status').output
    for action in ['install','uninstall']:
        assert '源码环境' in cmd('cli',action,code=1).output
    assert '0.' in cmd('--version').output


@pytest.mark.parametrize('options',[
    ['--check','--status'],['--check','--yes'],['--status','--yes']])
def test_update_conflicting_options_are_json_errors(isolated,options):
    result=cmd('update',*options,'--json',code=2)
    assert json.loads(result.output)['error']['code']=='invalid_arguments'


def test_update_human_output_and_saved_status(isolated,monkeypatch):
    from src.core.update_manager import UpdateManager,UpdateResult,Installation,UpdateError
    assert json.loads(cmd('update','--status','--json').output)['status']
    monkeypatch.setattr(UpdateManager,'check',lambda *_a,**_k: UpdateResult(
        status='up_to_date',channel='stable',current_version='0.2.5',latest_version='0.2.5',
        installation=Installation('source','python','. ',False),can_install=False,message='已是最新'))
    result=cmd('update','--check')
    assert '已是最新' in result.output and '0.2.5' in result.output
    def failed(*_a,**_k):raise UpdateError('network','服务不可用')
    monkeypatch.setattr(UpdateManager,'check',failed)
    assert json.loads(cmd('update','--check','--json',code=1).output)['error']['code']=='network'
    monkeypatch.setattr(UpdateManager,'check',lambda *_a,**_k: (_ for _ in ()).throw(OSError('socket closed')))
    assert 'socket closed' in cmd('update','--check',code=1).output


def test_config_nested_values_redaction_and_explicit_deletion(isolated):
    cmd('config','set','editor.nested.enabled','false')
    cmd('config','set','editor.nested.count','12')
    cmd('config','set','editor.nested.label','plain')
    assert ConfigManager().config['editor']['nested']=={'enabled':False,'count':12,'label':'plain'}
    assert '12' in cmd('config','get','editor.nested.count').output
    cmd('config','get','missing.path',code=1)
    cmd('config','set','ai_settings','{"api_key":"PRIVATE123","model":"demo","base_url":"https://example.test"}')
    cmd('config','set','github_settings','{"token":"TOKEN123"}')
    for key in ['ai_settings','github_settings']:
        output=cmd('config','get',key).output
        assert 'PRIVATE123' not in output and 'TOKEN123' not in output
        assert '******' in output
    # Dot paths traverse scalar parents without losing the encryption route.
    cmd('config','set','ai_settings.extra','1')
    cmd('config','set','ai_settings.extra.flag','true')
    assert ConfigManager().get_ai_settings()['extra']=={'flag':True}
    cmd('config','set','custom_credentials','{}',code=1)
    cmd('config','set','custom_credentials.sample','CUSTOM123')
    for key in ['custom_credentials','custom_credentials.sample']:
        assert 'CUSTOM123' not in cmd('config','get',key).output
    cmd('config','get','custom_credentials.absent',code=2)
    cmd('config','unset','custom_credentials',code=2)
    cmd('config','unset','custom_credentials.sample')
    cmd('config','unset','custom_credentials.absent',code=2)
    assert 'CUSTOM123' not in cmd('config','show').output
    cmd('config','unset','editor')
    assert 'editor' not in ConfigManager().config
    cmd('config','unset','editor',code=1)


@pytest.mark.parametrize('terminal',[False,True])
def test_real_run_human_summary_reports_and_stats(isolated,monkeypatch,tmp_path,terminal):
    import src.cli as cli
    monkeypatch.setattr(cli.console,'_force_terminal',terminal)
    _,source,_=isolated
    report=tmp_path/'report.json'
    result=cmd('run','--name','demo','--input','message=hello','--args','bad','--verbose','--output',report)
    assert '成功' in result.output
    data=json.loads(report.read_text(encoding='utf-8'))
    assert data['success'] and data['nodes'][0]['input']['message']=='hello'
    assert '总运行次数' in cmd('workflow','stats').output
    assert '执行摘要' in cmd('config','show').output
    cmd('run',source,'--input','[]')
    for value in ['{broken','bad']:
        cmd('run',source,'--input',value,code=1)
    cmd('run',source,'--node','missing',code=2)
    assert '执行报告' in cmd('run',source).output
    cmd('run',source,'--output',tmp_path,code=1)


@pytest.mark.parametrize('as_json',[False,True])
def test_run_path_and_input_errors_are_actionable(isolated,tmp_path,as_json):
    _,source,_=isolated
    suffix=['--json'] if as_json else []
    for args in [[],['--name','absent'],[tmp_path],[tmp_path/'missing'],[source,'--node','absent']]:
        result=cmd('run',*args,*suffix,code=1 if as_json or '--node' not in args else 2)
        if as_json:assert json.loads(result.output)['success'] is False
    source.write_text('{broken')
    result=cmd('run',source,*suffix,code=1)
    if as_json:assert '加载工作流失败' in json.loads(result.output)['error']


def test_cli_schedule_pause_resume_missing_and_failure_report(isolated):
    from src.core.headless_scheduler import HeadlessScheduler
    _,source,_=isolated
    scheduler=HeadlessScheduler()
    task=scheduler.add_task('demo',str(source),'0 * * * *')
    cmd('schedule','pause',task)
    assert ConfigManager().get_scheduled_task(task)['enabled'] is False
    cmd('schedule','resume',task)
    assert ConfigManager().get_scheduled_task(task)['enabled'] is True
    for action in ['pause','resume','run']:cmd('schedule',action,'missing',code=1)
    source.unlink()
    assert '失败' in cmd('schedule','run',task,code=1).output


def test_workflow_statistics_empty_then_failed_history(isolated):
    assert '暂无执行记录' in cmd('workflow','stats').output
    manager=ConfigManager()
    manager.add_execution_record({'id':'failed-run','workflow_name':'failed','status':'failed','duration_ms':12})
    output=cmd('workflow','stats').output
    assert 'failed' in output and '12ms' in output


def test_serve_routes_use_real_workflow_and_schedule_services(isolated,monkeypatch):
    from fastapi.testclient import TestClient
    from src.core.runtime_client import RuntimeClient
    monkeypatch.setattr(RuntimeClient,'ensure_running',lambda *_a,**_k: False)
    _,source,_=isolated
    observed=[]
    def run_server(api,**options):
        with TestClient(api) as client:
            assert client.get('/health').json()=={'status':'ok','service':'mozikit'}
            workflows=client.get('/workflows').json()['workflows']
            assert len(workflows)==1 and workflows[0]['name']=='demo'
            assert client.post('/workflows/run',params={'path':'missing'}).status_code==404
            assert client.post('/workflows/run',params={'path':str(source),'input_data':'broken'}).status_code==400
            result=client.post('/workflows/run',params={'path':str(source),'input_data':'{"value":42}'}).json()
            assert result['success'] is True and result['run_id']
            assert ConfigManager().get_execution_history()[0]['id']==result['run_id']
            assert client.post('/tasks',params={'workflow_path':'missing'}).status_code==404
            assert client.post('/tasks',params={'workflow_path':str(source),'cron':'bad'}).status_code==400
            task=client.post('/tasks',params={'workflow_path':str(source)}).json()['task_id']
            assert client.get('/tasks').json()['tasks'][0]['id']==task
            assert client.delete('/tasks/'+task).json()['status']=='deleted'
            assert client.delete('/tasks/'+task).status_code==404
            source.write_text('{broken')
            assert client.post('/workflows/run',params={'path':str(source)}).status_code==400
            write_document(source,{'workflow_name':'broken','nodes':[{'node_id':'a'}],'edges':[]})
            assert client.post('/workflows/run',params={'path':str(source)}).status_code==500
        observed.append(options)
        raise KeyboardInterrupt
    monkeypatch.setattr('uvicorn.run',run_server)
    assert '服务已停止' in cmd('serve','--host','127.0.0.1','--port','5055').output
    assert observed[0]['port']==5055
