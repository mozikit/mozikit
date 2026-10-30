from copy import deepcopy
import json
from pathlib import Path
import os
import signal
import subprocess
import sys
import time

from src.core.config_manager import ConfigManager
from src.core.workflow_lifecycle import write_document
from src.core.workflow_executor import WorkflowExecutor
from src.core.execution_snapshots import ExecutionSnapshots
from .world import REPO

DRIVERS={}
def driver(*names):
    def register(function):
        for name in names: DRIVERS[name]=function
        return function
    return register


def report(w,*options,code=0,real=None):
    result=w.cmd('run',w.source,'--json',*options,code=code,real=real)
    return json.loads(result.output)


@driver('full-run','target-run','report','failure-run','gui-history','history-missing','headless')
def execution(w,variant):
    action=w.contract['action']
    w.graph()
    if action=='history-missing':
        manager=ConfigManager()
        if variant=='startup':
            manager.add_execution_record({'id':'startup','status':'failed','artifact_dir':'','error':'launch failed'})
            w.cmd('workflow','history','show','startup')
            w.eq('startup failure preserved',json.loads(w.last.output)['status'],'failed')
        elif variant=='artifact':
            manager.add_execution_record({'id':'lost','status':'success','artifact_dir':str(w.root/'gone')})
            w.cmd('workflow','history','show','lost',code=1)
            w.eq('missing report explained','不存在' in w.last.output or 'No such file' in w.last.output,True)
        else:
            w.cmd('workflow','history','show','unknown',code=1)
            w.eq('unknown run explained','不存在' in w.last.output,True)
        return
    if action=='headless':
        # Poison Qt imports in a fresh process. A single attempted import fails the run.
        source='''import sys
class RejectQt:
 def find_spec(self,name,*args):
  if name=='PySide6' or name.startswith('PySide6.'):raise AssertionError('CLI attempted Qt import')
sys.meta_path.insert(0,RejectQt())
sys.path.insert(0,sys.argv.pop(1))
from src.cli import run_cli
run_cli()
'''
        env=dict(os.environ,PYTHONPATH=str(REPO))
        result=subprocess.run([sys.executable,'-c',source,str(REPO),'run',str(w.source),'--json'],env=env,cwd=w.root,capture_output=True,text=True,timeout=20)
        w.eq('fresh CLI no Qt import',result.returncode,0)
        w.eq('headless execution succeeded',json.loads(result.stdout)['success'],True)
        return
    if action=='failure-run':
        original=WorkflowExecutor._execute_node_with_details
        calls=[]
        def fail(executor,node_id,*args):
            calls.append(node_id)
            if node_id=='b': raise ValueError('controlled node resource failure')
            return original(executor,node_id,*args)
        w.monkeypatch.setattr(WorkflowExecutor,'_execute_node_with_details',fail)
        result=report(w,code=1,real=False)
        w.eq('failure reported',result['success'],False)
        w.eq('downstream not executed','c' in calls,False)
        w.eq('failure history retained',ConfigManager().get_execution_history()[0]['status'],'failed')
        return
    if action=='target-run':
        result=report(w,'--node','c')
        w.eq('exact subgraph',result['execution_order'],['a','b','c'])
        w.eq('all selected nodes executed',[n['node_id'] for n in result['nodes']],['a','b','c'])
        return
    if action=='report':
        data={'text':'x'*5000,'typed':[False,30,'30',{'x':True}]}
        output=w.root/'full-report.json'
        result=report(w,'--input',json.dumps(data),'--output',str(output))
        stored=json.loads(output.read_text())
        w.eq('full output preserved',stored['nodes'][0]['output']['value'],data)
        w.eq('stdout core report matches',result['nodes'],stored['nodes'])
        w.cmd('workflow','history','show',result['run_id'])
        w.eq('history report roundtrip',json.loads(w.last.output),stored)
        return
    result=report(w,real=False)
    if action=='gui-history':
        window,_=w.gui()
        overview=window.tabs.widget(0)
        overview._load_execution_history()
        seen=[]
        original=window.show_execution_report
        def observed(value):
            seen.append(value);return original(value)
        w.monkeypatch.setattr(window,'show_execution_report',observed)
        overview.history_table.cellWidget(0,4).click()
        w.eq('real history button loaded same report',seen[0]['run_id'],result['run_id'])
        w.eq('real history report nodes',seen[0]['nodes'],result['nodes'])
    else:
        _,widget=w.gui()
        widget._execute_workflow()
        gui=w.wait_worker(widget)
        w.eq('same actual node set',sorted(n['node_id'] for n in gui['nodes']),sorted(n['node_id'] for n in result['nodes']))
        w.eq('same outputs',{n['node_id']:n['output'] for n in gui['nodes']},{n['node_id']:n['output'] for n in result['nodes']})
        w.eq('GUI succeeded',gui['success'],True)


@driver('prepare-interrupt')
def prepare_interrupt(w,variant):
    calls=[]
    def interrupted(executor,*args,**kwargs):
        raise KeyboardInterrupt
    original=WorkflowExecutor._execute_node_with_details
    def observed(executor,node_id,*args):
        calls.append(node_id)
        return original(executor,node_id,*args)
    w.monkeypatch.setattr(WorkflowExecutor,'prepare_environment',interrupted)
    w.monkeypatch.setattr(WorkflowExecutor,'_execute_node_with_details',observed)
    w.cmd('run',w.source,'--json',code=130,real=False)
    w.eq('no node began',calls,[])


@driver('interrupt')
def interrupt(w,variant):
    from src.core.custom_node_manager import CustomNodeManager
    from src.core.node_registry import get_registry
    registry=get_registry()
    manager=CustomNodeManager(registry._user_data_dir)
    source="def execute(self,input_data):\n    from pathlib import Path\n    import time\n    import os\n    (Path(os.environ['MOZIKIT_WORKFLOW_DIR'])/'started').write_text('1')\n    time.sleep(60)\n    return input_data\n"
    definition=manager.create_generated_node('long-running','cancellation fixture',source,dependencies=[])
    registry.register_external_node(definition)
    document=deepcopy(w.document)
    document['nodes'][0].update(node_type=definition.node_type,config={'_safety_confirmed':True})
    write_document(w.source,document)
    env=dict(os.environ,PYTHONPATH=str(REPO))
    daemon=subprocess.Popen([sys.executable,'-m','src.core.runtime_daemon'],cwd=w.root,env=env,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
    w.processes.append(daemon)
    connection=w.root/'data'/'runtime'/'connection.json'
    deadline=time.monotonic()+15
    while not connection.exists() and daemon.poll() is None and time.monotonic()<deadline:time.sleep(.02)
    assert connection.exists(),'isolated daemon failed to start'
    output=w.root/'interrupt.stdout';error=w.root/'interrupt.stderr'
    with output.open('w') as out,error.open('w') as err:
        flags=subprocess.CREATE_NEW_PROCESS_GROUP if os.name=='nt' else 0
        process=subprocess.Popen([sys.executable,'-c','from src.cli import run_cli;run_cli()','run',str(w.source),'--json'],
                                 cwd=w.root,env=env,stdout=out,stderr=err,creationflags=flags)
        w.processes.append(process)
        started=w.source.parent/'started'
        deadline=time.monotonic()+25
        while not started.exists() and process.poll() is None and time.monotonic()<deadline:time.sleep(.02)
        assert started.exists(),error.read_text()
        process.send_signal(signal.CTRL_BREAK_EVENT if os.name=='nt' else signal.SIGINT)
        code=process.wait(timeout=10)
    w.eq('interrupted run exit',code,130)
    reports=ConfigManager().get_execution_history()
    w.eq('stopped history',reports[0]['status'],'stopped')
    w.eq('daemon remains alive',daemon.poll(),None)
    w.cmd('runtime','status')
    w.cmd('runtime','stop')
    daemon.wait(timeout=10)


@driver('fresh','reuse','gui-reuse','cache-change','target-config','cache-invalid','cache-lossless')
def cache(w,variant):
    action=w.contract['action']
    w.graph()
    calls=[]
    mode={'value':'normal'}
    artifact=w.root/'artifact.txt';artifact.write_text('artifact')
    original=WorkflowExecutor._execute_node_with_details
    def observed(executor,node_id,*args):
        calls.append(node_id)
        if mode['value']=='failed' and node_id=='b':raise ValueError('controlled node failure')
        raw,node_report=original(executor,node_id,*args)
        if mode['value']=='stopped':executor.request_stop()
        if mode['value']=='lossy':raw['non_json']={1,2}
        if mode['value']=='artifact':raw['artifacts']={'file':str(artifact)}
        return raw,node_report
    w.monkeypatch.setattr(WorkflowExecutor,'_execute_node_with_details',observed)
    if action=='cache-invalid' and variant in ['failed','stopped','lossy']:mode['value']=variant
    if action=='cache-change' and variant=='artifact':mode['value']='artifact'
    data={'long':'x'*5000,'typed':[False,30,'30']}
    initial_code=1 if mode['value']=='failed' else 130 if mode['value']=='stopped' else 0
    first=report(w,'--input',json.dumps(data),code=initial_code,real=False)
    run_id=first['run_id']
    if action=='fresh':
        report(w,'--node','c','--input',json.dumps(data),real=False)
        w.eq('upstream executed again',calls.count('a'),2)
        w.eq('target executed again',calls.count('c'),2)
        return
    if action=='cache-lossless':
        path=ExecutionSnapshots()._path(run_id)
        stored=json.loads(path.read_text())
        w.eq('lossless output',stored['outputs']['a']['value'],data)
        if os.name!='nt':w.eq('private snapshot mode',path.stat().st_mode&0o777,0o600)
        return
    if action=='cache-change':
        doc=w.doc()
        if variant=='identity':doc['workflow_id']='other'
        elif variant=='graph':doc['edges'].pop()
        elif variant=='input':data['long']='changed'
        elif variant=='config':doc['nodes'][0]['config']['new']=4
        elif variant=='version':doc['nodes'][0]['version']='2.0.0'
        elif variant=='credential':doc['nodes'][0]['config']['secret']='{{credential.demo}}'
        elif variant=='artifact':artifact.unlink()
        elif variant=='source':
            from src.core.node_registry import get_registry
            get_registry().get_node('debug').source_code='# changed source'
        else:
            path=w.source.parent/'.venv'/'lib'/'example.dist-info'/'METADATA'
            path.parent.mkdir(parents=True);path.write_text('Version: changed')
        write_document(w.source,doc)
    if action=='target-config':
        doc=w.doc();doc['nodes'][2]['config']['max_length']=999;write_document(w.source,doc)
    if action=='cache-invalid':
        path=ExecutionSnapshots()._path(run_id)
        if variant in ['unknown','display']:run_id='old-display-only'
        elif variant=='missing':path.unlink()
    rejected=action in ['cache-change','cache-invalid']
    before=len(calls)
    second=report(w,'--node','c','--reuse-run',run_id,'--input',json.dumps(data),code=1 if rejected else 0,real=False)
    if rejected:
        w.eq('no fallback executions',len(calls),before)
        w.eq('error explained',bool(second.get('error')),True)
        return
    w.eq('upstream a executed once',calls.count('a'),1)
    w.eq('upstream b executed once',calls.count('b'),1)
    w.eq('target c executed twice',calls.count('c'),2)
    w.eq('actual reused node set',[n['node_id'] for n in second['nodes'] if n.get('reused')],['a','b'])
    w.eq('full upstream data restored',second['nodes'][-1]['input'],next(n['input'] for n in first['nodes'] if n['node_id']=='c'))
    if action=='gui-reuse':
        _,widget=w.gui()
        widget.execute_single_node('c');initial=w.wait_worker(widget)
        saved_calls=len(calls)
        widget.execute_single_node('c');gui=w.wait_worker(widget)
        w.eq('GUI only reruns target',calls[saved_calls:],['c'])
        w.eq('GUI reused same upstream set',[n['node_id'] for n in gui['nodes'] if n.get('reused')],['a','b'])
