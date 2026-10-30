from copy import deepcopy
import base64
import hashlib
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
from threading import Event,Thread
import time
from types import SimpleNamespace

from src.core.config_manager import ConfigManager
from src.core.workflow_lifecycle import WorkflowLifecycle,write_document
from .world import REPO

DRIVERS={}
def driver(*names):
    def register(function):
        for name in names:DRIVERS[name]=function
        return function
    return register


def ai_server(w):
    generated={'name':'AcceptanceNode','description':'generated test node','source_code':'def execute(self,input_data):\n    return {"total":5}\n',
               'config_schema':{'count':{'type':'int','default':30}},'dependencies':[],'category':'Acceptance','version':'2.4.0'}
    state={'status':200,'generated':generated,'mode':'generation','requests':[],'timeout':False}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            payload=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            state['requests'].append(payload)
            if state['timeout']:time.sleep(1.3)
            body={'model':'acceptance','choices':[{'message':{'content':json.dumps(state['generated'])}}]}
            if state['mode']=='invalid':body=[]
            if state['mode']=='json':body={'choices':[{'message':{'content':'not JSON'}}]}
            self.send_response(state['status']);self.send_header('Content-Type','application/json');self.end_headers()
            try:self.wfile.write(json.dumps(body).encode())
            except (OSError,BrokenPipeError):pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=Thread(target=lambda:server.serve_forever(poll_interval=.02),daemon=True);thread.start()
    w.servers.append((server,thread))
    manager=ConfigManager();manager.set_ai_settings({'base_url':f'http://127.0.0.1:{server.server_port}/v1',
                                                  'api_key':'SAMPLE-KEY','model':'acceptance','timeout_seconds':1})
    return state


@driver('ai-fields','gui-ai','ai-version','ai-failure','ai-legacy','ai-probe')
def ai(w,variant):
    action=w.contract['action']
    state=ai_server(w)
    if action=='ai-probe':
        if variant=='auth':state['status']=401
        if variant=='invalid':state['mode']='invalid'
        w.cmd('config','test-ai',code=0 if variant=='success' else 1,real=False)
        result=json.loads(w.last.output)
        w.eq('probe status',result['success'],variant=='success')
        w.eq('probe does not leak key','SAMPLE-KEY' in w.last.output,False)
        return
    if action=='ai-legacy':state['generated'].pop('version')
    if action=='ai-failure':
        if variant=='auth':state['status']=401
        elif variant=='timeout':state['timeout']=True
        elif variant=='json':state['mode']='json'
        elif variant=='syntax':state['generated']['source_code']='def broken('
        elif variant=='safety':state['generated']['source_code']='def execute(self,input_data):\n    import os\n    os.system("echo forbidden")\n    return {}\n'
        else:
            import builtins
            original=builtins.open
            def denied(file,*args,**kwargs):
                if str(file).endswith('node.py') and args and 'w' in args[0]:raise PermissionError('injected node write failure')
                return original(file,*args,**kwargs)
            w.monkeypatch.setattr(builtins,'open',denied)
    before=set((w.root/'user_data').rglob('node.json')) if (w.root/'user_data').exists() else set()
    args=['node','generate','统计节点','--desc','汇总输入','--input','JSON 数组','--output','total 对象','--constraints','仅标准库']
    if action!='ai-legacy':args+=['--example-input','[{"value":2},{"value":3}]','--example-output','{"total":5}']
    w.cmd(*args,code=1 if action=='ai-failure' else 0,real=False)
    w.eq('key not printed','SAMPLE-KEY' in w.last.output,False)
    if action=='ai-failure':
        after=set((w.root/'user_data').rglob('node.json')) if (w.root/'user_data').exists() else set()
        w.eq('failed generation no new definitions',after,before)
        return
    generated=list((w.root/'user_data').rglob('node.json'))
    assert generated,('No real generated node persisted',w.last.exit_code,w.last.output)
    definition=json.loads(generated[0].read_text())
    expected_version='1.0.0' if action=='ai-legacy' else '2.4.0'
    w.eq('generated version persisted',definition['version'],expected_version)
    w.eq('version directory',generated[0].parent.name,expected_version)
    w.cmd('node','info',definition['node_type'],real=True)
    w.eq('fresh process loaded correct version',expected_version in w.last.output,True)
    prompt=json.loads(state['requests'][0]['messages'][1]['content'])
    if action!='ai-legacy':
        w.eq('input example sent',prompt['example_input'],'[{"value":2},{"value":3}]')
        w.eq('output example sent',prompt['example_output'],'{"total":5}')
    else:w.eq('legacy example empty',prompt['example_input'],'')
    if action=='gui-ai':
        from src.dialogs.add_node_dialog import AddNodeDialog
        from PySide6.QtWidgets import QMessageBox
        for method in ['warning','critical','information']:
            w.monkeypatch.setattr(QMessageBox,method,lambda *a,**k:QMessageBox.StandardButton.Ok)
        dialog=AddNodeDialog()
        dialog.ai_name_input.setText('统计节点');dialog.ai_desc_input.setPlainText('汇总输入')
        dialog.ai_input_spec.setPlainText('JSON 数组');dialog.ai_output_spec.setPlainText('total 对象')
        dialog.ai_constraints_input.setPlainText('仅标准库')
        dialog.ai_example_input.setPlainText('[{"value":2},{"value":3}]');dialog.ai_example_output.setPlainText('{"total":5}')
        dialog.ai_generate_btn.click()
        worker=dialog.generate_worker
        deadline=time.monotonic()+10
        while worker and worker.isRunning() and time.monotonic()<deadline:
            w.application.processEvents();worker.wait(5)
        if worker:worker.wait()
        w.application.processEvents()
        w.eq('GUI sent real HTTP request',len(state['requests']),2)
        w.eq('GUI and CLI input prompt',json.loads(state['requests'][1]['messages'][1]['content']),prompt)
        w.eq('both nodes persisted',len(list((w.root/'user_data').rglob('node.json'))),2)
        dialog.deleteLater()


def playwright_fixture(w):
    from src.core.custom_node_manager import CustomNodeManager
    from src.core.node_registry import get_registry
    registry=get_registry()
    definition=CustomNodeManager(registry._user_data_dir).create_playwright_node('Recorder','acceptance','print("{{name}}")')
    registry.register_external_node(definition)
    document=deepcopy(w.document)
    document['nodes'][0].update(node_type=definition.node_type,config={'script_source':'print("{{name}} {{legacy}}")',
        'param_schema':{'name':{'type':'string'},'legacy':{'type':'string'}},'name':'Alice','legacy':'remove-me'})
    write_document(w.source,document)
    return document


@driver('gui-script','script-life','script-invalid','record','record-failure','gui-runtime','tool-install','tool-failure')
def playwright(w,variant):
    from src.core.playwright_runtime import PlaywrightRuntime
    action=w.contract['action']
    if action in ['tool-install','tool-failure','gui-runtime']:
        runtime=PlaywrightRuntime(w.root/'中文 tools')
        before=w.source.read_bytes()
        commands=[]
        w.monkeypatch.setattr('src.core.uv_manager.UVManager.get_preferred_uv_path',lambda self:None if variant=='uv' else 'uv')
        w.monkeypatch.setattr('src.core.uv_manager.UVManager.get_current_mirror',lambda self:'https://packages.example.test/simple')
        if action=='tool-install' and variant!='source':
            w.monkeypatch.setattr(sys,'frozen',True,raising=False)
            w.monkeypatch.setattr(sys,'executable',str(w.root/'mozikit.exe'))
        if action=='tool-failure':
            runtime.root.mkdir();(runtime.root/'current.json').write_text('{"version":"old"}')
        def tool(command,cancel=None):
            commands.append(command)
            if action=='tool-failure':raise PermissionError('write failure') if variant=='write' else RuntimeError('package endpoint failure')
            if command[1]=='venv':
                python=runtime.python_in(Path(command[2]));python.parent.mkdir(parents=True);python.touch()
        w.monkeypatch.setattr(runtime,'_run',tool)
        if action=='tool-failure':
            try:runtime.install()
            except (OSError,RuntimeError,ValueError):pass
            else:raise AssertionError('installation failure not exercised')
            w.eq('old runtime pointer unchanged',json.loads((runtime.root/'current.json').read_text()),{'version':'old'})
        else:
            runtime.install()
            w.eq('install uses real tool Python',commands[1][commands[1].index('--python')+1],str(runtime.python()))
            w.eq('EXE never used as Python',all('mozikit.exe' not in ' '.join(command) for command in commands),True)
            if action=='gui-runtime':
                w.monkeypatch.setattr('src.core.playwright_runtime.PlaywrightRuntime',lambda:runtime)
                w.monkeypatch.setattr(runtime,'available',lambda:True)
                from src.dialogs.playwright_script_dialog import PlaywrightScriptDialog
                dialog=PlaywrightScriptDialog()
                w.eq('GUI discovers same tool environment',dialog._check_and_install_playwright(),True)
                w.eq('same environment object',dialog._playwright_runtime is runtime,True)
                command=runtime.recording_command(w.root/'record.py')
                w.eq('space and Unicode command path',command[0],str(runtime.python()))
                dialog.deleteLater()
        w.eq('tool install never changes workflow',w.source.read_bytes(),before)
        return
    document=playwright_fixture(w)
    before=w.source.read_bytes()
    script=w.root/'script.py';script.write_text('print("{{name}}")',encoding='utf-8')
    if action=='script-invalid':
        node='a'
        if variant=='syntax':script.write_text('def broken(')
        elif variant=='empty':script.write_text('   ')
        elif variant=='missing':node='missing'
        else:
            document['nodes'][0]['node_type']='debug';write_document(w.source,document);before=w.source.read_bytes()
        w.cmd('workflow','script','set',str(w.source),node,str(script),code=1,real=False)
        w.eq('invalid script leaves original bytes',w.source.read_bytes(),before)
        return
    if action=='script-life':
        w.cmd('workflow','script','show',w.source,'a',real=False)
        w.eq('show reads original source',w.last.output.strip(),document['nodes'][0]['config']['script_source'])
        w.cmd('workflow','script','validate',w.source,'a',real=False)
        w.eq('validate is read only',w.source.read_bytes(),before)
        w.cmd('workflow','script','rescan',w.source,'a',real=False)
        w.cmd('workflow','script','clear',w.source,'a',real=False)
        config=w.doc()['nodes'][0]['config']
        w.eq('clear removes script',config['script_source'],'')
        w.eq('clear removes unused parameter','name' in config,False)
        w.cmd('workflow','script','validate',w.source,'a',code=1,real=False)
        return
    if action=='gui-script':
        # Real modal editor result flows through the actual properties widget.
        from src.views.node_properties import NodePropertiesWidget
        panel=NodePropertiesWidget();node_type=document['nodes'][0]['node_type']
        panel.load_node_properties('a',node_type,deepcopy(document['nodes'][0]['config']))
        panel._do_load_node_properties()
        panel._apply_playwright_script_result({'script_source':'print("{{name}}")','param_schema':{'name':{'type':'string'}}})
        gui=deepcopy(panel.current_config)
        w.cmd('workflow','script','set',w.source,'a',script,real=False)
        actual=w.doc()['nodes'][0]['config']
        w.eq('GUI and CLI script',gui['script_source'],actual['script_source'])
        w.eq('kept parameter value',actual['name'],'Alice')
        w.eq('removed old parameter','legacy' in actual,False)
        panel.deleteLater()
        return
    # The process boundary is controlled; command resolution, validation and saving are real.
    commands=[]
    w.monkeypatch.setattr(PlaywrightRuntime,'available',lambda self:True)
    w.monkeypatch.setattr(PlaywrightRuntime,'python',lambda self:w.root/'tool environment'/'python')
    def codegen(command,**kwargs):
        commands.append(command)
        if action=='record-failure' and variant=='interrupt':raise KeyboardInterrupt
        if action=='record-failure' and variant=='start':raise FileNotFoundError('codegen')
        if action=='record-failure' and variant=='exit':raise subprocess.CalledProcessError(1,command)
        output=Path(command[command.index('-o')+1])
        if action=='record-failure' and variant=='missing':return SimpleNamespace(returncode=0)
        text='def invalid(' if variant=='syntax' else '   ' if variant=='empty' else 'print("{{name}}")'
        output.write_text(text,encoding='utf-8')
        return SimpleNamespace(returncode=0)
    w.monkeypatch.setattr(subprocess,'run',codegen)
    expected=130 if action=='record-failure' and variant=='interrupt' else 1 if action=='record-failure' else 0
    w.cmd('workflow','script','record',w.source,'a','--url','https://example.test',code=expected,real=False)
    if action=='record-failure':w.eq('failed recording leaves bytes unchanged',w.source.read_bytes(),before)
    else:
        w.eq('tool Python used',commands[0][0],str(w.root/'tool environment'/'python'))
        w.eq('chrome channel selected',commands[0][commands[0].index('--channel')+1],'chrome')
        w.eq('recording saved after validation',w.doc()['nodes'][0]['config']['script_source'],'print("{{name}}")')


@driver('retry','write-failure','concurrent','save-order','windows-save','ci-branches','ci-sha','ci-coverage','ci-incomplete','ci-performance')
def persistence(w,variant):
    action=w.contract['action']
    if action in ['retry','write-failure']:
        import src.core._file_utils as files
        target=w.root/'atomic.json';target.write_text('old')
        original=files.os.replace
        attempts=[]
        def external_replace(source,destination):
            attempts.append(1)
            if action=='write-failure' or len(attempts)<3:raise PermissionError('injected busy file')
            return original(source,destination)
        w.monkeypatch.setattr(files.os,'replace',external_replace)
        w.monkeypatch.setattr(files.time,'sleep',lambda duration:None)
        try:files.atomic_write(target,'new')
        except PermissionError:
            if action!='write-failure':raise
        w.eq('file result',target.read_text(),'new' if action=='retry' else 'old')
        w.eq('bounded attempts',len(attempts),3 if action=='retry' else 6)
        w.eq('temporary files cleaned',list(w.root.glob('*.tmp')),[])
    elif action=='concurrent':
        script='import sys;sys.path.insert(0,sys.argv[1]);from src.core.config_manager import ConfigManager;m=ConfigManager();m.config[sys.argv[2]]=True;m.save_config();m.add_execution_record({"id":sys.argv[2],"status":"success"})'
        processes=[subprocess.Popen([sys.executable,'-c',script,str(REPO),str(index)],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL) for index in range(8)]
        w.processes.extend(processes)
        w.eq('all writer processes succeeded',[process.wait(timeout=20) for process in processes],[0]*8)
        actual=ConfigManager().config
        w.eq('all different configuration keys committed',all(actual.get(str(i)) is True for i in range(8)),True)
        w.eq('all different history IDs committed',{record['id'] for record in actual['execution_history']},{str(i) for i in range(8)})
    elif action in ['save-order','windows-save']:
        manager=ConfigManager();manager.config['options']={'keep':1,'delete':2};manager.save_config()
        stale=ConfigManager()
        del manager.config['options']['delete'];manager.save_config_sync()
        stale.config['other']=3;stale.save_config()
        w.eq('explicit deletion not resurrected',ConfigManager().config,{'options':{'keep':1},'other':3})
        if action=='windows-save':
            for i in range(10):manager.config['iteration']=i;manager.save_config_sync()
            w.eq('repeated Windows persistence',ConfigManager().config['iteration'],9)
    elif action=='ci-branches':
        for filename in ['test_linux.yml','test_windows.yml']:
            text=(REPO/'.github/workflows'/filename).read_text()
            w.eq(filename+' dev trigger','branches: [ main, dev ]' in text,True)
            w.eq(filename+' no accidental develop-only trigger','main, develop' in text,False)
    elif action=='ci-sha':
        from tools.check_release_checks import ready
        sha='a'*40
        runs=[{'id':i,'name':name,'head_sha':sha,'status':'completed','conclusion':'success'} for i,name in enumerate(['Test (Linux)','Test (Windows)'],1)]
        if variant=='old-sha':runs[0]['head_sha']='b'*40
        elif variant=='windows-failed':runs[1]['conclusion']='failure'
        elif variant=='linux-missing':runs=runs[1:]
        elif variant=='running':runs[0]['status']='in_progress'
        w.eq('exact SHA release decision',ready(runs,sha),variant=='green')
    elif action=='ci-coverage':
        from tools.check_coverage import evaluate
        lines,branches=map(float,variant.split('/'))
        data={'files':{name:{'summary':{'covered_lines':int(lines*10),'num_statements':1000,'covered_branches':int(branches*10),'num_branches':1000}} for name in ['src/cli.py','src/cli_parity.py']}}
        w.eq('independent statement and branch thresholds',evaluate(data,core=False)[0]['passed'],lines>=85 and branches>=75)
    elif action=='ci-incomplete':
        from tools.check_acceptance import complete
        data={'required':[{'id':'WF_001'}],'results':[{'id':'WF_001','status':'passed','binding':'bound','assertions':2,'kind':'business'}]}
        if variant=='undefined':data['results'][0]['binding']='undefined'
        elif variant=='empty':data['results'][0]['assertions']=0
        elif variant=='skip':data['results'][0]['status']='skipped'
        elif variant=='help-only':data['results'][0]['kind']='help'
        elif variant=='packaged-missing':data.update(required_platforms=['windows-packaged'],platforms=['linux'])
        else:data.update(claims_live=True,live_evidence=[])
        w.eq('incomplete evidence rejected',complete(data),False)
    else:
        for filename in ['test_linux.yml','test_windows.yml']:
            text=(REPO/'.github/workflows'/filename).read_text()
            section=text.split('Run performance without coverage',1)[1].split('- name:',1)[0]
            w.eq(filename+' performance has no instrumentation','--cov' in section,False)
            w.eq(filename+' coverage artifact measured','--cov-branch' in text and 'check_coverage.py' in text,True)


def wait_for(predicate,seconds=12):
    deadline=time.monotonic()+seconds
    while time.monotonic()<deadline:
        value=predicate()
        if value:return value
        time.sleep(.03)
    raise AssertionError('Business state did not converge within deadline')


@driver('schedule-target','gui-schedule','schedule-invalid','schedule-life','trigger-life','watch','activation-failure','gui-trigger')
def scheduling(w,variant):
    action=w.contract['action']
    beta=w.workspace/'beta'/'workflow.json'
    write_document(beta,{**w.document,'workflow_name':'beta','workflow_id':'beta-stable'})
    from src.core.headless_scheduler import HeadlessScheduler
    scheduler=HeadlessScheduler()
    if action in ['schedule-target','gui-schedule','schedule-invalid','schedule-life']:
        task_id=scheduler.add_task('demo',str(w.source))
        if action=='schedule-invalid':
            before=ConfigManager().get_scheduled_task(task_id)
            target=w.root/'missing.json' if variant=='missing' else beta
            if variant=='json':target=w.root/'invalid.json';target.write_text('not JSON')
            cron='invalid' if variant=='cron' else '5 * * * *'
            w.cmd('schedule','update',task_id,'--workflow',target,'--cron',cron,code=1,real=False)
            w.eq('schedule transaction unchanged',ConfigManager().get_scheduled_task(task_id),before)
            return
        if action=='schedule-life':
            w.cmd('schedule','list')
            w.cmd('schedule','update',task_id,'--name','Display label','--cron','5 * * * *')
            w.eq('name alone preserves target',ConfigManager().get_scheduled_task(task_id)['workflow_path'],str(w.source))
            w.cmd('schedule','pause',task_id)
            w.eq('pause persisted',ConfigManager().get_scheduled_task(task_id)['enabled'],False)
            w.cmd('schedule','resume',task_id)
            w.eq('resume persisted',ConfigManager().get_scheduled_task(task_id)['enabled'],True)
            w.cmd('schedule','run',task_id)
            w.eq('task really executed',ConfigManager().get_execution_history()[0]['workflow_name'],'demo')
            w.cmd('schedule','remove',task_id)
            w.eq('task deleted',ConfigManager().get_scheduled_task(task_id),None)
            return
        w.cmd('schedule','update',task_id,'--workflow',beta,'--cron','5 * * * *',real=False)
        cli=ConfigManager().get_scheduled_task(task_id)
        w.eq('same task identity',cli['id'],task_id)
        w.eq('new task target name',cli['workflow_name'],'beta')
        w.eq('new task target path',cli['workflow_path'],str(beta))
        w.cmd('schedule','run',task_id,real=False)
        w.eq('actual new execution target',ConfigManager().get_execution_history()[0]['workflow_name'],'beta')
        if action=='gui-schedule':
            from PySide6.QtWidgets import QDialog
            from src.views.overview_widget import AddScheduledTaskDialog
            second=scheduler.add_task('demo',str(w.source))
            def accept(dialog):
                dialog.workflow_combo.setCurrentIndex(dialog.workflow_combo.findText('beta'))
                dialog.schedule_type.setCurrentIndex(1);dialog.cron_input.setText('5 * * * *')
                return QDialog.DialogCode.Accepted
            w.monkeypatch.setattr(AddScheduledTaskDialog,'exec',accept)
            window,_=w.gui()
            window.tabs.widget(0)._on_edit_scheduled_task(ConfigManager().get_scheduled_task(second))
            gui=ConfigManager().get_scheduled_task(second)
            for key in ['workflow_name','workflow_path','cron_expression','enabled']:
                w.eq('same schedule '+key,gui[key],cli[key])
        return
    old=w.source.parent/'old-watch';new=w.source.parent/'new-watch'
    old.mkdir();new.mkdir()
    w.cmd('workflow','trigger','add','demo','folder_watch','--id','watch','--path',old,
          '--event','created','--include','*.sav','--settle','0','--debounce','100',real=False)
    if action=='trigger-life':
        w.cmd('workflow','trigger','show','demo','watch')
        w.cmd('workflow','trigger','set','demo','watch','--path',new)
        w.cmd('workflow','trigger','disable','demo','watch')
        w.eq('trigger disabled',w.doc()['triggers'][0]['enabled'],False)
        w.cmd('workflow','trigger','enable','demo','watch')
        w.eq('trigger enabled',w.doc()['triggers'][0]['enabled'],True)
        w.cmd('workflow','trigger','list','demo','--json')
        w.cmd('workflow','trigger','status','demo','--json')
        w.cmd('workflow','trigger','remove','demo','watch')
        w.eq('trigger removed',w.doc()['triggers'],[])
        w.eq('other workflow data retained',w.doc()['nodes'],w.document['nodes'])
        return
    if action=='activation-failure':
        def denied(*a,**k):raise RuntimeError('controlled daemon startup failure')
        w.monkeypatch.setattr('src.core.runtime_client.RuntimeClient.ensure_running',denied)
        w.cmd('workflow','activate','demo',code=1,real=False)
        w.eq('activation rolled back',w.doc()['active'],False)
        return
    w.cmd('workflow','activate','demo',real=True)
    def status():
        result=w.cmd('workflow','status','demo','--json',real=True)
        value=json.loads(result.output)
        return value if value['triggers'] and value['triggers'][0]['status']=='running' else None
    observed=wait_for(status)
    if action=='gui-trigger':
        window,widget=w.gui()
        window._poll_trigger_runtime()
        w.eq('GUI activity equals CLI',widget.executor.active,observed['active'])
        w.eq('GUI actual trigger state',widget.trigger_items['watch'].runtime_status.get('status'),observed['triggers'][0]['status'])
        return
    (old/'initial.sav').write_text('created')
    wait_for(lambda:ConfigManager().get_execution_history())
    w.cmd('workflow','trigger','set','demo','watch','--path',new,real=True)
    def coordinated():
        value=json.loads(w.cmd('workflow','status','demo','--json',real=True).output)
        return (value['triggers'][0].get('runtime_config') or {}).get('path')==str(new)
    wait_for(coordinated)
    baseline=len(ConfigManager().get_execution_history())
    (old/'not-observed.sav').write_text('old')
    time.sleep(.4)
    w.eq('old directory no longer triggers',len(ConfigManager().get_execution_history()),baseline)
    (new/'observed.sav').write_text('new')
    wait_for(lambda:len(ConfigManager().get_execution_history())>baseline)
    w.cmd('workflow','deactivate','demo',real=True)
    wait_for(lambda:json.loads(w.cmd('workflow','status','demo','--json',real=True).output)['triggers'][0]['status']=='stopped')
    baseline=len(ConfigManager().get_execution_history())
    (new/'after-stop.sav').write_text('stopped')
    time.sleep(.4)
    w.eq('deactivated source cannot trigger',len(ConfigManager().get_execution_history()),baseline)


class GitHubTransport:
    def __init__(self,files=None):
        self.files=files or {}
        self.failed=False
        self.requests=[]

    def path(self,url):
        from urllib.parse import urlsplit,unquote
        path=unquote(urlsplit(url).path)
        return path.split('/contents/',1)[1] if '/contents/' in path else ''

    def get(self,url,*a,**k):
        self.requests.append(('GET',url))
        if self.failed:return 401,{'message':'controlled authorization failure'}
        path=self.path(url)
        if path in self.files:
            text=self.files[path]
            from src.core.workflow_sync import compute_blob_sha
            return 200,{'type':'file','name':Path(path).name,'path':path,'sha':compute_blob_sha(text),
                        'content':base64.b64encode(text.encode()).decode(),'encoding':'base64'}
        prefix=path.rstrip('/')+'/' if path else ''
        children={key[len(prefix):].split('/')[0] for key in self.files if key.startswith(prefix)}
        if not children:return 404,{'message':'not found'}
        return 200,[{'name':name,'path':prefix+name,'type':'file' if prefix+name in self.files else 'dir'} for name in sorted(children)]

    def put(self,url,token,data,*a,**k):
        self.requests.append(('PUT',url))
        if self.failed:return 401,{'message':'controlled authorization failure'}
        path=self.path(url)
        self.files[path]=base64.b64decode(data['content']).decode('utf-8')
        return 201,{'content':{'path':path}}


def remote_nodes(w):
    files={'manifest.json':json.dumps({'nodes':['one','two']})}
    for name in ['one','two']:
        files[name+'/node.json']=json.dumps({'node_type':'github_'+name,'name':name,'description':'Acceptance',
            'version':'1.0.0','entry_file':'node.py','config_schema':{},'dependencies':[]})
        files[name+'/node.py']='def execute(self, input_data):\n    return input_data\n'
    transport=GitHubTransport(files)
    w.monkeypatch.setattr('src.core.providers.github_provider._gh_get',transport.get)
    return transport


def remote_official(w):
    definition={'node_type':'acceptance_official','name':'Official acceptance','version':'2.0.0','entry_file':'node.py','config_schema':{},'dependencies':[]}
    manifest={'repo_name':'acceptance-official','repo_version':'2.0.0','nodes':{'acceptance_official':{'versions':[
        {'version':'2.0.0','files':{'node.json':{},'node.py':{}}}]}}}
    transport=GitHubTransport({'manifest.json':json.dumps(manifest),
        'versions/acceptance_official/2.0.0/node.json':json.dumps(definition),
        'versions/acceptance_official/2.0.0/node.py':'def execute(self, input_data):\n    return input_data\n'})
    w.monkeypatch.setattr('src.core.node_repo_manager._gh_get',transport.get)
    return transport


def remote_sync(w):
    transport=GitHubTransport()
    w.monkeypatch.setattr('src.core.workflow_sync._gh_get',transport.get)
    w.monkeypatch.setattr('src.core.workflow_sync._gh_put',transport.put)
    manager=ConfigManager();manager.set_github_settings({'token':'SAMPLE-GH','connected':True})
    w.cmd('workflow','sync','config','--repo','acceptance/workflows','--branch','feature','--path','flows',real=False)
    return transport


@driver('zip','source-invalid','gui-usage','github-nodes','official','sync','credential','oauth','uv','remote-failure','mcp')
def integrations(w,variant):
    action=w.contract['action']
    from src.core.node_registry import get_registry
    from src.core.custom_node_manager import CustomNodeManager
    if action in ['zip','source-invalid']:
        definition=CustomNodeManager(get_registry()._user_data_dir).create_node('Acceptance','zip fixture')
        get_registry().register_external_node(definition)
        source=w.root/'node.py';source.write_text('def execute(self, input_data):\n    return {"value":42}\n')
        if action=='source-invalid':
            original=get_registry().get_display_source_code(definition.node_type)
            source.write_text('def broken(')
            w.cmd('node','source','set',definition.node_type,source,code=1,real=False)
            w.eq('invalid source not persisted',get_registry().get_display_source_code(definition.node_type),original)
            return
        w.cmd('node','source','set',definition.node_type,source,real=False)
        exported=w.root/'node.zip'
        w.cmd('node','export',definition.node_type,exported,'--all',real=False)
        w.eq('real ZIP exists',exported.is_file(),True)
        w.cmd('node','delete',definition.node_type,real=False)
        w.cmd('node','import',exported,real=False)
        w.cmd('node','source','show',definition.node_type,real=False)
        w.eq('ZIP restores source',w.last.output.strip(),source.read_text().strip())
        w.cmd('node','delete',definition.node_type,real=False)
        w.eq('registry entry removed',get_registry().get_node(definition.node_type),None)
    elif action=='gui-usage':
        w.graph();write_document(w.workspace/'second'/'workflow.json',{**w.document,'workflow_name':'second','workflow_id':'second'})
        w.cmd('node','usage','debug',real=False)
        usage=json.loads(w.last.output)
        w.eq('both workflows counted',sorted((item['workflow_name'],item['count']) for item in usage),[('demo',4),('second',4)])
        window,_=w.gui();browser=window.findChild(__import__('src.views.node_browser',fromlist=['NodeBrowserWidget']).NodeBrowserWidget)
        browser._update_usage_list('debug')
        w.eq('real GUI usage rows',browser.usage_list.count(),len(usage))
    elif action=='github-nodes':
        transport=remote_nodes(w)
        url='https://github.com/acceptance/nodes'
        w.cmd('node','github','import',url,real=False)
        w.cmd('node','github','list',real=False)
        w.eq('two nodes registered',len(json.loads(w.last.output)[url]),2)
        data=json.loads(transport.files['one/node.json']);data['version']='2.0.0';transport.files['one/node.json']=json.dumps(data)
        w.cmd('node','github','update',url,real=False)
        w.eq('updated version registered',get_registry().get_node('github_one').version,'2.0.0')
        w.cmd('node','info','github_one',real=True)
        w.eq('fresh process loads new version','2.0.0' in w.last.output,True)
        w.cmd('node','github','remove',url,real=False)
        w.eq('only repository nodes removed',get_registry().get_node('github_one'),None)
        w.eq('builtins retained',get_registry().get_node('debug') is not None,True)
    elif action=='official':
        transport=remote_official(w)
        w.cmd('node','repo','check-updates',real=False)
        w.eq('checking does not install',get_registry().get_node('acceptance_official'),None)
        w.cmd('node','repo','install','acceptance_official','--version','2.0.0',real=False)
        w.cmd('node','info','acceptance_official',real=True)
        w.eq('installed version usable by new process','2.0.0' in w.last.output,True)
    elif action=='sync':
        transport=remote_sync(w)
        w.cmd('workflow','sync','push','demo',real=False)
        w.cmd('workflow','sync','status','demo',real=False)
        w.cmd('workflow','sync','list',real=False)
        w.eq('branch and path used',any('flows/demo/workflow.json' in request[1] for request in transport.requests),True)
        remote=json.loads(transport.files['flows/demo/workflow.json']);remote['nodes'][0]['config']['updated']=True
        transport.files['flows/demo/workflow.json']=json.dumps(remote)
        w.cmd('workflow','sync','pull','demo',real=False)
        w.eq('pulled exact workflow',w.doc(),remote)
    elif action=='credential':
        secret=w.root/'value.txt';secret.write_text('SAMPLE-SECRET\n')
        w.cmd('credential','set','acceptance','--value-file',secret)
        w.eq('credential stdout masked','SAMPLE-SECRET' in w.last.output,False)
        w.eq('configuration not plaintext','SAMPLE-SECRET' in (w.root/'data'/'config.json').read_text(),False)
        w.cmd('credential','list');w.eq('fresh process sees credential','acceptance' in w.last.output,True)
        w.cmd('config','get','custom_credentials.acceptance');w.eq('get hides credential','SAMPLE-SECRET' in w.last.output,False)
        w.cmd('credential','remove','acceptance')
        w.cmd('credential','list');w.eq('deleted reference not resurrected','acceptance' in json.loads(w.last.output),False)
    elif action=='oauth':
        import urllib.request
        def oauth_http(request,**kwargs):
            url=request.full_url
            if 'device/code' in url:body={'device_code':'fixture-device','user_code':'ABCD-EFGH','verification_uri':'https://example.test/verify','expires_in':60,'interval':1}
            elif 'access_token' in url:body={'access_token':'SAMPLE-GH'}
            else:body={'login':'acceptance-user'}
            return io.BytesIO(json.dumps(body).encode())
        w.monkeypatch.setattr(urllib.request,'urlopen',oauth_http)
        w.monkeypatch.setattr('webbrowser.open',lambda url:True)
        w.cmd('config','github-login','--timeout','5',real=False)
        w.eq('OAuth token protected','SAMPLE-GH' in (w.root/'data'/'config.json').read_text(),False)
        w.eq('fresh manager decrypts intended token',ConfigManager().get_github_token(),'SAMPLE-GH')
        w.cmd('config','github-logout',real=False)
        w.eq('logout clears token',ConfigManager().get_github_token(),'')
    elif action=='uv':
        from src.core.uv_manager import UVManager
        executable=w.root/'uv executable';executable.touch()
        w.monkeypatch.setattr(UVManager,'_verify_uv_executable',lambda *args:True)
        w.monkeypatch.setenv('UV_INDEX_URL','https://initial.example.test/simple')
        calls=[]
        def uv_process(command,**kwargs):
            calls.append(command)
            if 'venv' in command:
                Path(command[command.index('venv')+1]).mkdir(parents=True,exist_ok=True)
            return SimpleNamespace(returncode=0,stdout='',stderr='')
        w.cmd('env','set-uv-path',executable,real=False)
        w.cmd('env','set-mirror','https://packages.example.test/simple',real=False)
        w.monkeypatch.setattr(subprocess,'run',uv_process)
        w.cmd('env','create','tools',real=False)
        w.cmd('env','install','tools','requests',real=False)
        w.cmd('env','list',real=False)
        w.cmd('env','remove','tools',real=False)
        installs=[command for command in calls if 'install' in command]
        w.eq('UV path persisted',ConfigManager().config['uv_path'],str(executable))
        w.eq('mirror persisted',ConfigManager().config['uv_mirror'],'https://packages.example.test/simple')
        w.eq('real install argv gets mirror',installs[0][installs[0].index('--index-url')+1],'https://packages.example.test/simple')
        w.eq('only own environment removed',(w.workspace/'tools'/'.venv').exists(),False)
    elif action=='remote-failure':
        before=w.source.read_bytes()
        if variant.startswith('github-'):
            transport=remote_nodes(w)
            if variant=='github-update':w.cmd('node','github','import','https://github.com/acceptance/nodes',real=False)
            paths={str(path):path.read_bytes() for path in (w.root/'user_data').rglob('*') if path.is_file() and not path.name.endswith('.lock')}
            transport.failed=True
            w.cmd('node','github','import' if variant=='github-import' else 'update','https://github.com/acceptance/nodes',code=1,real=False)
            w.eq('installed node files preserved',{str(path):path.read_bytes() for path in (w.root/'user_data').rglob('*') if path.is_file() and not path.name.endswith('.lock')},paths)
        elif variant=='official-install':
            transport=remote_official(w);transport.failed=True
            w.cmd('node','repo','install','acceptance_official',code=1,real=False)
        else:
            transport=remote_sync(w);transport.failed=True
            w.cmd('workflow','sync','push' if variant=='sync-push' else 'pull','demo',code=1,real=False)
        w.eq('workflow not destroyed',w.source.read_bytes(),before)
        w.eq('token not printed','SAMPLE-GH' in w.last.output,False)
    elif action=='mcp':
        from src.core.mcp_server_registry import MCPServerRegistry,MCPServerDefinition
        from test.integration.test_mcp_client_manager_sdk import SERVER_CODE
        script=w.root/'mcp_server.py';script.write_text(SERVER_CODE.replace('import anyio', 'import anyio\nfrom pydantic import BaseModel').replace('def echo(value: int) -> dict:\n    return {"value": value}', 'class EchoResult(BaseModel):\n    value: int\n\ndef echo(value: int) -> EchoResult:\n    return EchoResult(value=value)').replace('description="Echo a value")','description="Echo a value", structured_output=True)'))
        MCPServerRegistry().add_server(MCPServerDefinition('local','Acceptance',stdio={'command':sys.executable,'args':['-u',str(script)]}))
        document=w.graph();document['nodes'][0].update(node_type='mcp_tool',config={'server_id':'local','tool_name':'echo','arguments':{'value':7}})
        for edge in document['edges']:
            if edge['from_node']=='a':edge['from_port']='result'
        write_document(w.source,document)
        w.cmd('run',w.source,'--json',real=True)
        report=json.loads(w.last.output)
        w.eq('actual SDK tool result',report['nodes'][0]['output']['result'],{'value':7})
        second=next(node for node in report['nodes'] if node['node_id']=='b')
        w.eq('MCP result enters downstream',second['input']['input'],{'value':7})
    else:
        raise AssertionError('Live acceptance must be provided by an explicit external test environment')
