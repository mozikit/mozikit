"""Real artifact entry points and explicitly attributed manual observations.

Never substitute a source interpreter for a packaged executable. Missing external
prerequisites are blocked; supplied but inconsistent evidence fails acceptance.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess

import pytest

from .world import REPO

MANIFEST_ENV='MOZIKIT_ACCEPTANCE_EXTERNAL_MANIFEST'
DRIVERS={}


def manifest():
    location=os.environ.get(MANIFEST_ENV)
    if not location:
        pytest.skip('BLOCKED: provide '+MANIFEST_ENV+' with same-commit artifacts and/or live evidence; see acceptance/README.md')
    path=Path(location).resolve()
    data=json.loads(path.read_text(encoding='utf-8'))
    sha=subprocess.check_output(['git','rev-parse','HEAD'],cwd=REPO,text=True).strip()
    assert data['source_ref']==sha,'External evidence must belong to the tested commit'
    assert data.get('operator'),'External evidence needs an accountable operator'
    from datetime import datetime
    observed=datetime.fromisoformat(data['observed_at'].replace('Z','+00:00'))
    assert observed.tzinfo is not None,'Use an explicit UTC/timezone timestamp'
    data['_base']=path.parent
    return data


def evidence_file(data,entry):
    path=Path(entry['path'])
    if not path.is_absolute():path=data['_base']/path
    assert path.is_file(),'Missing evidence file: '+str(path)
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(1024*1024),b''):digest.update(chunk)
    assert digest.hexdigest()==entry['sha256'],'Changed evidence file: '+str(path)
    return path


def package(data,kind):
    entry=data.get('packages',{}).get(kind)
    if entry is None:pytest.skip('BLOCKED: no actual '+kind+' installation/artifact supplied')
    evidence_file(data,entry['distribution'])
    executable=evidence_file(data,entry['cli'])
    desktop=evidence_file(data,entry['desktop'])
    assert executable.name.lower()=='mozikit.exe'
    assert desktop.name.lower()=='mozikitdesktop.exe' and desktop.parent==executable.parent
    assert (executable.parent/'runtime'/'uv.exe').is_file()
    return executable


def command(w,exe,*args,code=0,timeout=60):
    env=dict(os.environ)
    for key in ['PYTHONPATH','PYTHONHOME','VIRTUAL_ENV']:
        env.pop(key,None)
    system=Path(env['SystemRoot'])
    env['PYTHONUTF8']='1'
    env['UV_PYTHON_PREFERENCE']='only-managed'
    env['UV_PYTHON_INSTALL_DIR']=str(w.root/'managed-python')
    env['PATH']=os.pathsep.join(map(str,[system/'System32',system,exe.parent/'runtime']))
    result=subprocess.run([str(exe),*map(str,args)],cwd=w.root,env=env,capture_output=True,
                          text=True,encoding='utf-8',timeout=timeout)
    w.eq('actual frozen CLI exit code',result.returncode,code)
    assert result.returncode==code,(result.stdout,result.stderr)
    return result.stdout


def manual(w,data,key,observations):
    record=data.get('observations',{}).get(key)
    if record is None:pytest.skip('BLOCKED: missing manual observations for '+key)
    assert record.get('mode')=='manual','Interactive evidence must remain identified as manual'
    assert record.get('files'),'Manual observation needs hashed evidence files'
    for entry in record['files']:evidence_file(data,entry)
    for name in observations:
        assert name in record,'Missing observation: '+name
        w.eq('manual observation: '+name,record[name],True)
    w.external_evidence={'mode':'manual','operator':data['operator'],
                         'observed_at':data['observed_at'],'files':record['files']}


def package_cli(w,variant):
    data=manifest();exe=package(data,variant)
    # Compare process IDs so an existing desktop instance cannot hide a GUI launch.
    def desktop_pids():
        import csv,io
        result=subprocess.run(['tasklist','/FI','IMAGENAME eq MozikitDesktop.exe','/FO','CSV','/NH'],
                              capture_output=True,text=True,check=True)
        return {row[1] for row in csv.reader(io.StringIO(result.stdout)) if len(row)>1 and row[0].lower()=='mozikitdesktop.exe'}
    before=desktop_pids()
    w.eq('frozen --help', 'workflow' in command(w,exe,'--help'),True)
    w.eq('frozen --version', bool(command(w,exe,'--version').strip()),True)
    name='中文工作流'
    command(w,exe,'workflow','create',name)
    w.eq('Unicode workflow persisted',w.doc(w.workspace/name/'workflow.json')['workflow_name'],name)
    status=json.loads(command(w,exe,'workflow','status',name,'--json'))
    w.eq('frozen JSON name',status['workflow_name'],name)
    w.eq('no desktop process launched',desktop_pids(),before)


def package_tool(w,variant):
    data=manifest();exe=package(data,variant)
    result=json.loads(command(w,exe,'workflow','script','install-runtime',timeout=600))
    interpreter=Path(result['python'])
    w.eq('private tool interpreter exists',interpreter.is_file(),True)
    w.eq('interpreter is not launcher',interpreter.resolve()==exe.resolve(),False)
    w.eq('tool directory owned by app data',interpreter.is_relative_to(w.root/'data'/'tools'/'playwright'),True)
    output=command(w,interpreter,'-m','playwright','--version')
    w.eq('real tool import', 'Version' in output,True)


def package_registration(w,variant):
    data=manifest()
    if not data.get('disposable_windows_host'):pytest.skip('BLOCKED: PATH acceptance requires a disposable Windows host')
    kind='portable' if w.contract['action']=='package-register' else 'msi'
    exe=package(data,kind)
    import winreg
    def read(root,key):
        try:
            with winreg.OpenKey(root,key) as handle:return winreg.QueryValueEx(handle,'Path')
        except FileNotFoundError:return None
    original=read(winreg.HKEY_CURRENT_USER,'Environment')
    system_key=r'SYSTEM\CurrentControlSet\Control\Session Manager\Environment'
    system=read(winreg.HKEY_LOCAL_MACHINE,system_key)
    from src.core.cli_registration import merge_path_entry,remove_path_entry
    try:
        if kind=='portable':
            # Use an unrelated entry to verify registration preserves neighbours.
            sentinel=str(w.root/'unrelated path')
            seeded=merge_path_entry(original[0] if original else '',sentinel)
            with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,'Environment',0,winreg.KEY_WRITE) as handle:
                winreg.SetValueEx(handle,'Path',0,original[1] if original else winreg.REG_EXPAND_SZ,seeded)
            command(w,exe,'cli','install','--json')
            command(w,exe,'cli','install','--json')
            changed=read(winreg.HKEY_CURRENT_USER,'Environment')[0]
            w.eq('only own PATH entry added',changed,merge_path_entry(seeded,str(exe.parent)))
            command(w,exe,'cli','uninstall','--json')
            w.eq('only own PATH entry removed',read(winreg.HKEY_CURRENT_USER,'Environment')[0],remove_path_entry(changed,str(exe.parent)))
        else:
            initial=json.loads(command(w,exe,'cli','status','--json'))
            assert 'system' in initial['locations'],'MSI must actually be installed with system PATH ownership'
            command(w,exe,'cli','install','--json');command(w,exe,'cli','uninstall','--json')
            status=json.loads(command(w,exe,'cli','status','--json'))
            w.eq('MSI registration survives CLI uninstall',status['source'],'installer')
        w.eq('system PATH unchanged',read(winreg.HKEY_LOCAL_MACHINE,system_key),system)
    finally:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER,'Environment',0,winreg.KEY_WRITE) as handle:
            if original:winreg.SetValueEx(handle,'Path',0,original[1],original[0])
            else:
                try:winreg.DeleteValue(handle,'Path')
                except FileNotFoundError:pass
        from src.core.cli_registration import _broadcast_environment_change
        _broadcast_environment_change()


def package_interactive(w,variant):
    data=manifest()
    action=w.contract['action']
    kind=variant if variant in ('msi','portable') else 'msi'
    exe=package(data,kind)
    w.eq('actual package update status is JSON',isinstance(json.loads(command(w,exe,'update','--status','--json')),dict),True)
    observations={
        'package-history':['cli_history_visible_in_gui','gui_report_readable_from_cli','shared_workspace_and_config'],
        'package-update':['check_does_not_install','confirmation_required','confirmed_handoff_exit_3'],
        'package-bad-hash':['hash_rejected','installer_not_started','user_data_unchanged'],
        'package-record':['chrome_really_recorded','script_written_back','parameters_rescanned','gui_execution_succeeded'],
    }[action]
    manual(w,data,w.contract_id+':'+variant,observations)


def live_services(w,variant):
    data=manifest()
    manual(w,data,'INT_012:default',['ai_generation','private_github_node','workflow_push_pull',
                                   'official_node_install','oauth_login_logout','external_mcp_tool'])


DRIVERS.update({'package-cli':package_cli,'package-tool':package_tool,
                'package-register':package_registration,'package-msi-path':package_registration,
                'package-history':package_interactive,'package-update':package_interactive,
                'package-bad-hash':package_interactive,'package-record':package_interactive,
                'live-services':live_services})
