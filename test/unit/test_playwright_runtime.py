import json
from pathlib import Path
import subprocess
import sys
from threading import Event

import pytest

from src.core.playwright_runtime import PlaywrightRuntime
from test.unit.test_parity_repairs import isolated


def test_install_targets_private_python_even_when_frozen(isolated, tmp_path, monkeypatch):
    manager = PlaywrightRuntime(tmp_path / '中文 tools')
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, 'executable', str(tmp_path / 'mozikit.exe'))
    monkeypatch.setattr('src.core.uv_manager.UVManager.get_preferred_uv_path', lambda self: 'uv')
    commands = []
    def run(command, cancel=None):
        commands.append(command)
        if command[1] == 'venv':
            python = manager.python_in(Path(command[2]))
            python.parent.mkdir(parents=True)
            python.touch()
    monkeypatch.setattr(manager, '_run', run)
    result = manager.install()
    assert result['status'] == 'ready'
    assert commands[1][commands[1].index('--python')+1] == str(manager.python())
    assert all(str(sys.executable) not in command for command in commands)
    assert manager.python().is_relative_to(manager.root)
    monkeypatch.setattr(manager, 'available', lambda: True)
    command = manager.recording_command(tmp_path / 'recording.py', 'https://example.test')
    assert command[:4] == [str(manager.python()), '-m', 'playwright', 'codegen']
    assert command[-1] == 'https://example.test'
    assert command[command.index('--channel')+1] == 'chrome'


def test_failed_install_keeps_previous_pointer(isolated, tmp_path, monkeypatch):
    manager = PlaywrightRuntime(tmp_path / 'tools')
    manager.root.mkdir()
    pointer = manager.root / 'current.json'
    pointer.write_text('{"version":"previous"}')
    monkeypatch.setattr('src.core.uv_manager.UVManager.get_preferred_uv_path', lambda self: 'uv')
    monkeypatch.setattr(manager, '_run', lambda *args: (_ for _ in ()).throw(RuntimeError('installation failed')))
    with pytest.raises(RuntimeError):
        manager.install()
    assert json.loads(pointer.read_text()) == {'version': 'previous'}
    assert not list((manager.root / 'versions').iterdir())


def test_missing_or_invalid_runtime_pointer(isolated, tmp_path):
    manager = PlaywrightRuntime(tmp_path)
    assert manager.python() is None and not manager.available()
    (tmp_path / 'current.json').write_text('{"version":"../outside"}')
    assert manager.python() is None
    with pytest.raises(ValueError, match='install-runtime'):
        manager.recording_command(tmp_path / 'output.py')


def test_cancellation_reaps_install_child(isolated, monkeypatch):
    processes = []
    original = subprocess.Popen
    def popen(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        return process
    monkeypatch.setattr(subprocess, 'Popen', popen)
    cancel = Event()
    cancel.set()
    with pytest.raises(InterruptedError):
        PlaywrightRuntime._run([sys.executable, '-c', 'import time;time.sleep(60)'], cancel)
    assert len(processes) == 1 and processes[0].poll() is not None


def test_install_process_success_failure_and_reuse(isolated, tmp_path, monkeypatch):
    # These are real children, including enough output to fill a pipe.
    PlaywrightRuntime._run([sys.executable,'-c','print("x" * 100000)'])
    with pytest.raises(RuntimeError,match='installation diagnostic'):
        PlaywrightRuntime._run([sys.executable,'-c','import sys;print("installation diagnostic");sys.exit(7)'])
    manager=PlaywrightRuntime(tmp_path/'runtime')
    python=manager.python_in(manager.root/'versions'/'ready')
    python.parent.mkdir(parents=True)
    python.touch()
    (manager.root/'current.json').write_text('{"version":"ready"}')
    monkeypatch.setattr(subprocess,'run',lambda *a,**k: subprocess.CompletedProcess(a[0],0))
    assert manager.available()
    assert manager.install()=={'status':'ready','python':str(python)}
    monkeypatch.setattr(subprocess,'run',lambda *a,**k: (_ for _ in ()).throw(OSError('missing loader')))
    assert not manager.available()
    monkeypatch.setattr(subprocess,'run',lambda *a,**k: subprocess.CompletedProcess(a[0],1))
    assert not manager.available()


def test_success_with_cancel_token_not_set(isolated):
    PlaywrightRuntime._run([sys.executable,'-c','pass'],Event())
