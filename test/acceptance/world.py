"""Acceptance fixtures observe real state; doubles stop at external boundaries."""
from contextlib import ExitStack
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shlex
import subprocess
import sys
import time
from types import SimpleNamespace

from typer.testing import CliRunner

from src.cli import app
from src.core.config_manager import ConfigManager
from src.core.workflow_lifecycle import WorkflowLifecycle, read_document, write_document, run_lock

REPO=Path(__file__).resolve().parents[2]


class World:
    def __init__(self, root, monkeypatch, application, real_process=False):
        self.root=root
        self.monkeypatch=monkeypatch
        self.application=application
        self.real_process=real_process
        monkeypatch.chdir(root)
        monkeypatch.setenv('MOZIKIT_WORKSPACE',str(root/'workflows'))
        monkeypatch.setenv('MOZIKIT_APP_DATA_DIR',str(root/'data'))
        monkeypatch.delenv('MOZIKIT_CONFIG_PATH',raising=False)
        from src.core import node_registry
        monkeypatch.setattr(node_registry,'_registry_instance',None)
        self.workspace=root/'workflows'
        self.source=self.workspace/'demo'/'workflow.json'
        self.document={'version':2,'workflow_id':'demo-stable','workflow_name':'demo','active':False,'triggers':[],
                       'nodes':[{'node_id':'a','node_type':'debug','config':{},'position':{'x':12,'y':34},'version':'1.0.0','extra':{'keep':True},'inputs':[],'outputs':[]}],
                       'edges':[],'canvas_state':{'scale_x':1.3,'offset_y':35},'extra':{'keep':[1,False]}}
        write_document(self.source,self.document)
        (self.source.parent/'input.csv').write_bytes(b'id,value\n1,42\n')
        self.checks=[]
        self.stack=ExitStack()
        self.windows=[]
        self.processes=[]
        self.servers=[]

    def eq(self,label,actual,expected):
        self.checks.append((label,actual,expected))

    def cmd(self,*args,code=0,real=None):
        if self.real_process if real is None else real:
            env=dict(os.environ,PYTHONPATH=str(REPO)+os.pathsep+os.environ.get('PYTHONPATH',''))
            raw=subprocess.run([sys.executable,'-c','from src.cli import run_cli;run_cli()',*map(str,args)],
                               cwd=self.root,env=env,capture_output=True,text=True,encoding='utf-8',timeout=30)
            result=SimpleNamespace(exit_code=raw.returncode,output=raw.stdout,stderr=raw.stderr)
        else:
            result=CliRunner().invoke(app,list(map(str,args)))
        self.eq('exit code: '+' '.join(map(str,args[:3])),result.exit_code,code)
        self.last=result
        return result

    def doc(self,path=None):
        return json.loads(Path(path or self.source).read_text(encoding='utf-8'))

    def graph(self):
        document=deepcopy(self.document)
        document['nodes']=[{'node_id':name,'node_type':'debug','config':{},'position':{'x':i*100,'y':20},'inputs':[],'outputs':[]} for i,name in enumerate(['a','b','c','sibling'])]
        document['edges']=[{'from_node':left,'from_port':'value','to_node':right,'to_port':'input'} for left,right in [('a','b'),('b','c'),('a','sibling')]]
        by_id={node['node_id']:node for node in document['nodes']}
        for edge in document['edges']:
            by_id[edge['from_node']]['outputs'].append(edge['to_node'])
            by_id[edge['to_node']]['inputs'].append(edge['from_node'])
        write_document(self.source,document)
        self.document=document
        return document

    def gui(self,source=None):
        from src.main_window import MainWindow
        from PySide6.QtWidgets import QMessageBox
        # Modal questions are an interaction boundary; real widgets/services still run.
        for method in ['warning','critical','information']:
            self.monkeypatch.setattr(QMessageBox,method,lambda *a,**k: QMessageBox.StandardButton.Ok)
        window=MainWindow()
        self.windows.append(window)
        source=Path(source or self.source)
        window.tabs.widget(0)._on_open_workflow(source.parent.name,str(source))
        window.show()
        self.application.processEvents()
        return window,window.tabs.currentWidget()

    def wait_worker(self,widget):
        worker=widget._run_worker
        assert worker is not None
        deadline=time.monotonic()+20
        while worker.isRunning() and time.monotonic()<deadline:
            self.application.processEvents()
            worker.wait(5)
        assert not worker.isRunning(),'GUI run did not finish'
        worker.wait()
        self.application.processEvents()
        records=ConfigManager().get_execution_history()
        assert records,'GUI execution did not persist history'
        return json.loads((Path(records[0]['artifact_dir'])/'run.json').read_text(encoding='utf-8'))

    def close(self):
        self.stack.close()
        if (self.root/'data'/'runtime'/'connection.json').exists():
            from src.core.runtime_client import RuntimeClient
            try: RuntimeClient(self.root/'data'/'runtime').stop_daemon()
            except (OSError,ValueError): pass
        for server,thread in self.servers:
            server.shutdown();server.server_close();thread.join(timeout=3)
        for process in self.processes:
            if process.poll() is None:
                process.terminate()
                try: process.wait(timeout=5)
                except subprocess.TimeoutExpired: process.kill();process.wait()
        for window in self.windows:
            for index in range(window.tabs.count()):
                widget=window.tabs.widget(index)
                if hasattr(widget,'_is_modified'): widget._is_modified=False
                worker=getattr(widget,'_run_worker',None)
                if worker and worker.isRunning(): worker.request_stop();worker.wait(5000)
            window.hide();window.deleteLater()
        if self.application:
            self.application.processEvents()

    def execute(self,action,variant):
        from . import workflow_cases, execution_cases, integration_cases, external_cases
        for module in (workflow_cases,execution_cases,integration_cases,external_cases):
            driver=module.DRIVERS.get(action)
            if driver:
                return driver(self,variant)
        raise AssertionError('Undefined acceptance business driver: '+action)
