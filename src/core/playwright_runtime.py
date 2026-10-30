"""One writable recorder environment shared by desktop and CLI launchers."""
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import uuid

from filelock import FileLock

from ._file_utils import atomic_write
from .runtime_paths import get_app_data_dir
from .uv_manager import UVManager


class PlaywrightRuntime:
    def __init__(self, root=None):
        self.root = Path(root or get_app_data_dir() / 'tools' / 'playwright').resolve()

    @staticmethod
    def python_in(directory):
        return directory / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')

    def python(self):
        try:
            version = json.loads((self.root / 'current.json').read_text(encoding='utf-8'))['version']
            if not isinstance(version, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]*', version):
                return None
            candidate = self.python_in(self.root / 'versions' / version)
            if candidate.is_file():
                return candidate
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def available(self):
        python = self.python()
        if not python:
            return False
        try:
            return subprocess.run([str(python), '-m', 'playwright', '--version'],
                                  capture_output=True, timeout=10).returncode == 0
        except (OSError, subprocess.SubprocessError):
            return False

    @staticmethod
    def _run(command, cancel=None):
        # A file avoids pipe deadlocks and keeps package manager chatter off JSON stdout.
        import tempfile
        with tempfile.TemporaryFile() as output:
            process = subprocess.Popen(command, stdout=output, stderr=subprocess.STDOUT)
            try:
                while process.poll() is None:
                    if cancel is not None and cancel.wait(0.1):
                        raise InterruptedError('Playwright 安装已取消')
                    if cancel is None:
                        try:
                            process.wait(timeout=0.1)
                        except subprocess.TimeoutExpired:
                            pass
                if process.returncode:
                    output.seek(0)
                    raise RuntimeError('Playwright 工具安装失败: ' + output.read().decode('utf-8', errors='replace')[-2000:])
            finally:
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait()

    def install(self, cancel=None):
        self.root.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.root / 'install.lock'), timeout=120):
            if self.available():
                return {'status': 'ready', 'python': str(self.python())}
            uv = UVManager().get_preferred_uv_path()
            if not uv:
                raise ValueError('请先安装或配置 UV: env install-uv')
            version = uuid.uuid4().hex
            directory = self.root / 'versions' / version
            directory.parent.mkdir(parents=True, exist_ok=True)
            python = self.python_in(directory)
            try:
                self._run([uv, 'venv', str(directory), '--python', '3.12'], cancel)
                command = [uv, 'pip', 'install', '--python', str(python), 'playwright']
                mirror = UVManager().get_current_mirror()
                if mirror:
                    command += ['--index-url', mirror]
                self._run(command, cancel)
                self._run([str(python), '-m', 'playwright', '--version'], cancel)
                atomic_write(self.root / 'current.json', json.dumps({'version': version}))
            except BaseException:
                shutil.rmtree(directory, ignore_errors=True)
                raise
            return {'status': 'ready', 'python': str(python)}

    def recording_command(self, output, url=''):
        if not self.available():
            raise ValueError('Playwright 工具环境不可用，请先执行 workflow script install-runtime')
        command = [str(self.python()), '-m', 'playwright', 'codegen', '--target', 'python',
                   '-o', str(output), '--browser', 'chromium', '--channel', 'chrome']
        return command + ([url] if url and url != 'https://' else [])
