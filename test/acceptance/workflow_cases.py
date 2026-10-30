from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
from unittest.mock import MagicMock

from src.core.config_manager import ConfigManager
from src.core.workflow_lifecycle import WorkflowLifecycle, write_document, run_lock
from .world import REPO

DRIVERS={}
def driver(*names):
    def register(function):
        for name in names: DRIVERS[name]=function
        return function
    return register


def references(w):
    manager=ConfigManager()
    manager.config.update(scheduled_tasks=[{'id':'mine','workflow_name':'demo','workflow_path':str(w.source),'enabled':True},
                                           {'id':'other','workflow_name':'other','workflow_path':'/unrelated/workflow.json','enabled':True}],
                          recent_workflows=[{'name':'demo','path':str(w.source)}],
                          execution_history=[{'id':'historical','workflow_name':'demo','artifact_dir':str(w.source.parent/'runs'/'old')}])
    manager.save_config_sync()
    return manager


@driver('rename','gui-rename')
def rename(w,variant):
    references(w)
    w.cmd('workflow','rename',w.source,'renamed')
    target=w.workspace/'renamed'
    w.eq('source moved',w.source.exists(),False)
    actual=w.doc(target/'workflow.json')
    for key in ['workflow_id','nodes','edges','extra','canvas_state']:
        w.eq('preserved '+key,actual[key],w.document[key])
    w.eq('asset bytes',(target/'input.csv').read_bytes(),b'id,value\n1,42\n')
    fresh=ConfigManager().config
    w.eq('schedule target',fresh['scheduled_tasks'][0]['workflow_path'],str(target/'workflow.json'))
    w.eq('historical name preserved',fresh['execution_history'][0]['workflow_name'],'demo')
    if w.contract['action']=='gui-rename':
        clone=w.workspace/'gui-demo'/'workflow.json'
        write_document(clone,{**w.document,'workflow_name':'gui-demo'})
        (clone.parent/'input.csv').write_bytes(b'id,value\n1,42\n')
        _,widget=w.gui(clone)
        widget.rename_workflow();widget.name_edit.setText('gui-renamed');widget.name_edit.editingFinished.emit()
        gui=w.doc(w.workspace/'gui-renamed'/'workflow.json')
        w.eq('GUI nodes',gui['nodes'],actual['nodes'])
        w.eq('GUI identity',gui['workflow_id'],actual['workflow_id'])
        w.eq('GUI resources',(w.workspace/'gui-renamed'/'input.csv').read_bytes(),(target/'input.csv').read_bytes())


@driver('invalid-name','gui-name')
def names(w,variant):
    from src.core.workflow_lifecycle import validate_workflow_name
    if w.contract['action']=='gui-name':variant=json.loads(variant)
    if w.contract['action']=='invalid-name':
        w.cmd('workflow','create',variant,code=1)
        w.eq('no outside creation',(w.root/'outside').exists(),False)
        w.eq('original bytes',w.doc(),w.document)
    else:
        _,widget=w.gui()
        valid,error=widget._validate_workflow_name(variant)
        expected=variant.strip()=='新流程'
        w.eq('GUI validity',valid,expected)
        result=w.cmd('workflow','create',variant,code=0 if expected else 1)
        if expected:
            w.eq('trimmed name',w.doc(w.workspace/'新流程'/'workflow.json')['workflow_name'],'新流程')
        else:
            w.eq('GUI explanation exists',bool(error),True)
            w.eq('original model unchanged',w.doc(),w.document)


@driver('delete-invalid')
def invalid_delete(w,variant):
    outside=w.root/'outside'/'workflow.json'
    invalid=w.workspace/'bad'/'workflow.json'
    write_document(outside,w.document);write_document(invalid,{})
    if variant=='root-json': write_document(w.workspace/'workflow.json',w.document)
    target={'text':w.source.parent/'input.csv','outside':outside,'root':w.workspace,
            'root-json':w.workspace/'workflow.json','invalid-json':invalid}[variant]
    w.cmd('workflow','delete',target,code=1)
    w.eq('original file',w.source.is_file(),True)
    w.eq('outside file',outside.is_file(),True)
    w.eq('asset bytes',(w.source.parent/'input.csv').read_bytes(),b'id,value\n1,42\n')


@driver('symlink')
def symlink(w,variant):
    outside=w.root/'outside'
    write_document(outside/'workflow.json',w.document)
    link=w.workspace/'link'
    try: link.symlink_to(outside,target_is_directory=True)
    except OSError:
        if os.name!='nt': raise
        subprocess.run(['cmd','/c','mklink','/J',str(link),str(outside)],check=True,capture_output=True)
    args=['workflow',variant,link/'workflow.json']+(['new'] if variant!='delete' else [])
    w.cmd(*args,code=1)
    w.eq('outside untouched',w.doc(outside/'workflow.json'),w.document)


@driver('delete')
def delete(w,variant):
    references(w)
    w.cmd('workflow','delete',w.source)
    w.eq('directory deleted',w.source.parent.exists(),False)
    fresh=ConfigManager().config
    w.eq('only own task disabled',[task['enabled'] for task in fresh['scheduled_tasks']],[False,True])
    w.eq('recent reference removed',fresh['recent_workflows'],[])
    w.eq('history retained',fresh['execution_history'][0]['id'],'historical')


@driver('rename-fault')
def rename_fault(w,variant):
    import src.core.workflow_lifecycle as module
    manager=references(w)
    before=deepcopy(manager.config)
    if variant=='move':
        original=Path.rename
        def fail(path,target):
            if path==w.source.parent: raise PermissionError('injected move error')
            return original(path,target)
        w.monkeypatch.setattr(Path,'rename',fail)
    elif variant=='document':
        original=module.write_document
        def fail(path,data):
            if Path(path)==w.workspace/'new'/'workflow.json': raise PermissionError('injected document error')
            return original(path,data)
        w.monkeypatch.setattr(module,'write_document',fail)
    else:
        original=manager.save_config_sync
        attempts=[]
        def fail():
            attempts.append(1)
            if len(attempts)==2: raise PermissionError('injected configuration error')
            return original()
        w.monkeypatch.setattr(manager,'save_config_sync',fail)
    try:
        WorkflowLifecycle(config_manager=manager).rename(w.source,'new')
    except PermissionError: pass
    else: raise AssertionError('Fault injection was not exercised')
    w.eq('original document',lambda:w.doc(),w.document)
    w.eq('original asset',lambda:(w.source.parent/'input.csv').read_bytes(),b'id,value\n1,42\n')
    w.eq('current references rolled back',lambda:ConfigManager().config,before)


@driver('recover')
def recover(w,variant):
    references(w)
    script='''import sys,os
from pathlib import Path
sys.path.insert(0,sys.argv[1])
import src.core.workflow_lifecycle as m
original=m.write_document
def interrupted(path,data):
    if Path(path).parent.name=='renamed' and Path(path).name=='workflow.json':os._exit(9)
    return original(path,data)
m.write_document=interrupted
m.WorkflowLifecycle().rename(sys.argv[2],'renamed')
'''
    result=subprocess.run([sys.executable,'-c',script,str(REPO),str(w.source)],capture_output=True,timeout=20)
    w.eq('process really interrupted',result.returncode,9)
    w.cmd('workflow','create','after-recovery')
    w.eq('restored original',w.doc(),w.document)
    w.eq('single original directory',(w.workspace/'renamed').exists(),False)
    w.eq('references restored',ConfigManager().get_scheduled_task('mine')['workflow_path'],str(w.source))


@driver('copy','exchange','collision')
def copy_exchange(w,variant):
    action=w.contract['action']
    if action=='collision':
        existing=w.workspace/'existing'/'workflow.json'
        write_document(existing,{**w.document,'workflow_name':'existing'})
        before=existing.read_bytes()
        args=['workflow',variant]+([w.source] if variant!='create' else [])
        args+=['--name','existing'] if variant=='import' else ['existing']
        w.cmd(*args,code=1)
        w.eq('target not overwritten',existing.read_bytes(),before)
        w.eq('source not altered',w.doc(),w.document)
        return
    if action=='copy':
        (w.source.parent/'.venv').mkdir();(w.source.parent/'runs').mkdir()
        source={**w.document,'active':True};write_document(w.source,source)
        w.cmd('workflow','copy',w.source,'copied')
        target=w.workspace/'copied'
        actual=w.doc(target/'workflow.json')
        w.eq('source unchanged',w.doc(),source)
        w.eq('copy new identity',actual['workflow_id']!=source['workflow_id'],True)
        w.eq('copy inactive',actual['active'],False)
        w.eq('copy layout',actual['nodes'],source['nodes'])
        w.eq('copied asset',(target/'input.csv').read_bytes(),(w.source.parent/'input.csv').read_bytes())
        w.eq('generated environments excluded',(target/'.venv').exists(),False)
        w.eq('generated history excluded',(target/'runs').exists(),False)
    else:
        exported=w.root/'exported.json'
        w.cmd('workflow','export',w.source,'--output',exported)
        w.cmd('workflow','import',exported,'--name','imported')
        actual=w.doc(w.workspace/'imported'/'workflow.json')
        w.eq('import new identity',actual['workflow_id']!=w.document['workflow_id'],True)
        w.eq('import inactive',actual['active'],False)
        w.eq('positions preserved',actual['nodes'],w.document['nodes'])
        w.eq('extension preserved',actual['extra'],w.document['extra'])
        w.eq('attachment boundary explained','附件' in w.last.output,True)


@driver('busy')
def busy(w,variant):
    state,operation=variant.split('-')
    document=deepcopy(w.document)
    if state=='active': document['active']=True;write_document(w.source,document)
    else: w.stack.enter_context(run_lock(document['workflow_id']))
    args=['workflow',operation,w.source]+(['new'] if operation=='rename' else [])
    w.cmd(*args,code=1,real=False)
    _,widget=w.gui()
    if operation=='rename':
        widget.rename_workflow();widget.name_edit.setText('new');widget.name_edit.editingFinished.emit()
    else:
        from PySide6.QtWidgets import QMessageBox
        w.monkeypatch.setattr(QMessageBox,'question',lambda *a,**kw:QMessageBox.StandardButton.Yes)
        w.windows[-1].tabs.widget(0)._on_delete_workflow('demo')
    w.eq('busy directory unchanged',w.doc(),document)


@driver('relocated')
def relocated(w,variant):
    from src.core.uv_manager import UVManager
    from src.core.node_base import NodeBase
    from src.core.workflow_executor import WorkflowExecutor
    old=w.source.parent/'.venv'
    old.mkdir();(old/'old-marker').touch()
    WorkflowLifecycle().rename(w.source,'renamed')
    manager=UVManager()
    calls=[]
    original=subprocess.run
    def external_tool(command,**kwargs):
        if 'venv' in command:
            path=Path(command[command.index('venv')+1]);path.mkdir(exist_ok=True)
            calls.append(command)
            return SimpleNamespace(returncode=0,stdout='',stderr='')
        return original(command,**kwargs)
    from types import SimpleNamespace
    w.monkeypatch.setattr(manager,'get_preferred_uv_path',lambda:'uv')
    w.monkeypatch.setattr(subprocess,'run',external_tool)
    ok=manager.create_workflow_env('renamed')
    w.eq('environment rebuilt',bool(calls) and ok,True)
    w.eq('old environment removed',(w.workspace/'renamed'/'.venv'/'old-marker').exists(),False)
    w.eq('relative asset intact',(w.workspace/'renamed'/'input.csv').read_bytes(),b'id,value\n1,42\n')
    w.eq('relocation marker cleared',w.doc(w.workspace/'renamed'/'workflow.json').get('environment_relocated',False),False)


@driver('external')
def external(w,variant):
    outside=w.root/'outside.json';write_document(outside,w.document);before=outside.read_bytes()
    w.cmd('run',outside,'--json')
    w.eq('external execution success',json.loads(w.last.output)['success'],True)
    for operation in ['validate','describe']:
        w.cmd('workflow',operation,outside)
    w.cmd('workflow','export',outside,'--output',w.root/'export.json')
    w.eq('source unchanged',outside.read_bytes(),before)


@driver('types','node-edit','replace-edge','invalid-edge','disconnect','gui-reopen')
def editing(w,variant):
    action=w.contract['action']
    w.graph()
    if action=='types':
        from src.core.node_registry import NodeDefinition,NodeSource,get_registry
        from PySide6.QtWidgets import QLineEdit,QSpinBox,QDoubleSpinBox,QCheckBox,QTextEdit
        from src.views.node_properties import NodePropertiesWidget
        kinds={'bool':('bool',False,'false'),'int':('int',30,'30'),'float':('float',1.25,'1.25'),
               'string':('string','30','"30"'),'array':('json',[1,2],'[1,2]'),'object':('json',{'x':True},'{"x":true}')}
        kind,value,encoded=kinds[variant]
        definition=NodeDefinition('acceptance-form','Acceptance','',NodeSource.OFFICIAL,'','',config_schema={'value':{'type':kind,'label':'Value'}})
        get_registry().register_external_node(definition)
        panel=NodePropertiesWidget();panel.load_node_properties('a','acceptance-form',{})
        panel._do_load_node_properties()
        editor=panel.config_widgets['value']
        if isinstance(editor,QCheckBox): editor.setChecked(value)
        elif isinstance(editor,(QSpinBox,QDoubleSpinBox)): editor.setValue(value)
        elif isinstance(editor,QTextEdit): editor.setPlainText(encoded)
        else: editor.setText(value)
        actual=panel._collect_current_config()['value']
        w.cmd('workflow','update-node',w.source,'a','value='+encoded,real=False)
        w.eq('Qt form and CLI value',actual,w.doc()['nodes'][0]['config']['value'])
        w.eq('value exact type',type(actual),type(value))
        panel.deleteLater()
    elif action=='node-edit':
        w.cmd('workflow','add-node',w.source,'debug','--x','300','--y','400')
        added=[n['node_id'] for n in w.doc()['nodes'] if n['node_id'] not in ['a','b','c','sibling']][0]
        w.cmd('workflow','update-node',w.source,added,'show_timestamp=false')
        w.cmd('workflow','remove-node',w.source,added)
        w.eq('other nodes retained',w.doc()['nodes'],w.document['nodes'])
    elif action=='replace-edge':
        w.cmd('workflow','connect',w.source,'b','sibling','--from-port','value')
        edges=[e for e in w.doc()['edges'] if e['to_node']=='sibling']
        w.eq('single new input edge',[(e['from_node'],e['to_node']) for e in edges],[('b','sibling')])
        _,widget=w.gui()
        widget._on_connection_created('a','output','sibling','input')
        w.eq('GUI also single input',len([e for e in widget.connections if e.to_node_id=='sibling']),1)
    elif action=='invalid-edge':
        before=w.source.read_bytes()
        args={'self':['a','a'],'source-port':['a','c','--from-port','missing'],
              'target-port':['a','c','--to-port','missing'],'missing-node':['missing','c'],
              'type':['a','c']}[variant]
        if variant=='type':
            from src.core.node_registry import get_registry
            definition=get_registry().get_node('debug')
            definition.input_schema={'input':{'type':'object'}}
            definition.output_schema={'output':{'type':'string'}}
        w.cmd('workflow','connect',w.source,*args,code=1,real=False)
        w.eq('invalid edge no write',w.source.read_bytes(),before)
    elif action=='disconnect':
        from src.core.node_registry import get_registry
        definition=get_registry().get_node('debug')
        definition.input_schema={'input':{'type':'any'},'second':{'type':'any'}}
        definition.output_schema={'output':{'type':'any'},'second':{'type':'any'}}
        w.cmd('workflow','connect',w.source,'a','b','--from-port','second','--to-port','second',real=False)
        w.cmd('workflow','disconnect',w.source,'a','b','--from-port','value',real=False)
        document=w.doc()
        w.eq('remaining parallel edge',any(e['from_node']=='a' and e['to_node']=='b' for e in document['edges']),True)
        b=next(n for n in document['nodes'] if n['node_id']=='b')
        w.eq('remaining adjacency','a' in b['inputs'],True)
    else:
        w.cmd('workflow','update-node',w.source,'a','max_length=500')
        _,widget=w.gui()
        w.eq('GUI loaded correct config',widget.nodes['a'].config['max_length'],500)
        widget._save_workflow_sync()
        w.eq('GUI resave keeps extension',w.doc()['extra'],w.document['extra'])
        w.eq('GUI resave keeps version',w.doc()['nodes'][0].get('version'),w.document['nodes'][0].get('version'))
