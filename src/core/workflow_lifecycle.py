"""Shared, journalled workflow directory operations for CLI and Qt."""
from contextlib import contextmanager
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path, PureWindowsPath
import re
import shutil
import uuid

from filelock import FileLock, Timeout

from . import resolve_workspace
from ._file_utils import atomic_write
from .config_manager import ConfigManager
from .config_transactions import merge_changes
from .runtime_paths import get_runtime_dir


def validate_workflow_name(value: str) -> str:
    name = value.strip()
    if not name or name in {'.', '..'} or name.endswith(('.', ' ')):
        raise ValueError('工作流名称不能为空、点号或以点号结尾')
    if re.search(r'[\\/:*?"<>|\x00-\x1f]', name) or PureWindowsPath(name).is_absolute():
        raise ValueError('工作流名称不能包含路径或非法字符')
    if name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *[f'{p}{i}' for p in ('COM', 'LPT') for i in range(1, 10)]}:
        raise ValueError('工作流名称不能使用系统保留名称')
    return name


def run_lock(workflow_id: str) -> FileLock:
    directory = get_runtime_dir() / 'run-locks'
    directory.mkdir(parents=True, exist_ok=True)
    key = hashlib.sha256(workflow_id.encode('utf-8')).hexdigest()
    return FileLock(str(directory / (key + '.lock')), timeout=0)


def read_document(path: Path) -> dict:
    if not path.is_file():
        raise FileNotFoundError(f'工作流文件不存在: {path}')
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except json.JSONDecodeError as exc:
        raise ValueError(f'JSON 解析失败: {exc}') from exc
    if not isinstance(data, dict) or not isinstance(data.get('workflow_name'), str):
        raise ValueError('工作流缺少有效名称 workflow_name')
    if not isinstance(data.get('nodes'), list) or not isinstance(data.get('edges'), list):
        raise ValueError('工作流缺少 nodes/edges 数组')
    ids = set()
    for node in data['nodes']:
        if not isinstance(node, dict) or not isinstance(node.get('node_id'), str) or not node['node_id'] or not isinstance(node.get('node_type'), str) or not isinstance(node.get('config', {}), dict):
            raise ValueError('工作流节点格式无效')
        if node['node_id'] in ids:
            raise ValueError('工作流节点 ID 重复')
        ids.add(node['node_id'])
    for edge in data['edges']:
        if isinstance(edge, dict):
            pair = (edge.get('from_node'), edge.get('to_node'))
        elif isinstance(edge, list) and len(edge) == 2:
            pair = edge
        else:
            raise ValueError('工作流连线格式无效')
        if any(not isinstance(node_id, str) or (node_id not in ids and not node_id.startswith('trigger:')) for node_id in pair):
            raise ValueError('工作流连线引用不存在的节点')
    return data


def write_document(path: Path, document: dict):
    atomic_write(path, json.dumps(document, ensure_ascii=False, indent=2))


class WorkflowLifecycle:
    GENERATED = {'.venv', '.runtime', 'scripts', 'runs', 'artifacts'}
    REFERENCES = ('scheduled_tasks', 'recent_workflows', 'execution_history')

    def __init__(self, workspace=None, config_manager=None):
        self.workspace = Path(workspace or resolve_workspace()).expanduser().resolve()
        self.config_manager = config_manager

    def owned(self, value) -> tuple[Path, dict]:
        raw = Path(value).expanduser()
        path = raw if raw.is_absolute() else (raw if raw.exists() else self.workspace / raw)
        if path.is_dir():
            path = path / 'workflow.json'
        path = path.resolve()
        if not path.exists():
            raise FileNotFoundError(f'工作流文件不存在: {path}')
        if path.name != 'workflow.json' or path.parent.parent != self.workspace or not path.is_file():
            raise ValueError('只能操作当前工作区内规范工作流目录中的 workflow.json')
        return path, read_document(path)

    def destination(self, name):
        name = validate_workflow_name(name)
        target = self.workspace / name
        if target.exists() or target.is_symlink():
            raise ValueError(f'工作流名称已存在: {name}')
        return target

    @contextmanager
    def locked(self):
        self.workspace.mkdir(parents=True, exist_ok=True)
        with FileLock(str(self.workspace / '.lifecycle.lock'), timeout=15):
            self.recover()
            yield

    def _manager(self):
        return self.config_manager or ConfigManager()

    def recover(self):
        journals = self.workspace / '.transactions'
        if not journals.exists():
            return
        for journal in journals.glob('*.json'):
            entry = json.loads(journal.read_text(encoding='utf-8'))
            source, target = Path(entry['source']), Path(entry['target'])
            if source.parent != self.workspace or target.parent != self.workspace:
                raise ValueError('事务记录路径越出工作区，停止恢复')
            if entry['phase'] == 'committed':
                if entry['operation'] == 'delete' and target.exists():
                    try:
                        shutil.rmtree(target)
                    except OSError:
                        # Logical deletion is durable; retry cleanup on the next visit.
                        continue
            else:
                if target.exists() and not source.exists():
                    target.rename(source)
                if source.exists():
                    write_document(source / 'workflow.json', entry['document'])
                manager = self._manager()
                manager.config = merge_changes(entry['after'], entry['before'], manager.config)
                manager.save_config_sync()
            journal.unlink()

    def create(self, name):
        with self.locked():
            target = self.destination(name)
            document = {'version': 2, 'workflow_id': str(uuid.uuid4()), 'workflow_name': target.name,
                        'active': False, 'triggers': [], 'nodes': [], 'edges': []}
            target.mkdir()
            try:
                write_document(target / 'workflow.json', document)
            except BaseException:
                shutil.rmtree(target)
                raise
            return target / 'workflow.json'

    def _references(self, manager, source, target, deleting):
        before = {key: deepcopy(manager.config[key]) for key in self.REFERENCES if key in manager.config}
        after = deepcopy(before)
        def relocated(value):
            if not value:
                return value
            try:
                relative = Path(value).resolve().relative_to(source)
            except ValueError:
                return value
            return str(target / relative)
        for task in after.get('scheduled_tasks', []):
            old = task.get('workflow_path')
            if relocated(old) != old:
                if deleting:
                    task['enabled'] = False
                else:
                    task.update(workflow_path=relocated(old), workflow_name=target.name)
        if deleting:
            after['recent_workflows'] = [item for item in after.get('recent_workflows', [])
                                         if relocated(item.get('path')) == item.get('path')]
        else:
            for item in after.get('recent_workflows', []):
                old = item.get('path')
                if relocated(old) != old:
                    item.update(path=relocated(old), name=target.name)
            for record in after.get('execution_history', []):
                for key in ('artifact_dir', 'workflow_path'):
                    if key in record:
                        record[key] = relocated(record[key])
        return before, after

    def _move(self, workflow, name=None):
        with self.locked():
            path, document = self.owned(workflow)
            if document.get('active'):
                raise ValueError('请先停用工作流监听后再重命名或删除')
            target = self.destination(name) if name is not None else self.workspace / ('.deleted-' + uuid.uuid4().hex)
            try:
                lock = run_lock(str(document.get('workflow_id') or path))
                with lock:
                    manager = self._manager()
                    with manager.transaction():
                        before, after = self._references(manager, path.parent, target, name is None)
                        journal = self.workspace / '.transactions' / (uuid.uuid4().hex + '.json')
                        entry = {'source': str(path.parent), 'target': str(target), 'document': document,
                                 'operation': 'rename' if name else 'delete', 'phase': 'prepared',
                                 'before': before, 'after': after}
                        write_document(journal, entry)
                        try:
                            path.parent.rename(target)
                            if name is not None:
                                updated = deepcopy(document)
                                if not updated.get('workflow_id'):
                                    updated['workflow_id'] = str(path)
                                updated['workflow_name'] = target.name
                                updated['environment_relocated'] = True
                                write_document(target / 'workflow.json', updated)
                            manager.config.update(after)
                            manager.save_config_sync()
                            entry['phase'] = 'committed'
                            write_document(journal, entry)
                        except BaseException:
                            self.recover()
                            raise
                    if name is None:
                        # The logical deletion is committed. Interrupted physical cleanup
                        # is recovered next time without resurrecting a partial directory.
                        try:
                            shutil.rmtree(target)
                        except OSError:
                            return None
                    journal.unlink(missing_ok=True)
                    return target / 'workflow.json' if name is not None else None
            except Timeout as exc:
                raise ValueError('工作流正在执行，请先停止') from exc

    def rename(self, workflow, name):
        return self._move(workflow, name)

    def delete(self, workflow):
        return self._move(workflow)

    def copy(self, workflow, name):
        with self.locked():
            path, document = self.owned(workflow)
            target = self.destination(name)
            for child in path.parent.rglob('*'):
                if child.is_symlink():
                    raise ValueError('复制不支持链接资源，请先将资源转换为实际文件')
            staging = self.workspace / ('.copy-' + uuid.uuid4().hex)
            try:
                shutil.copytree(path.parent, staging,
                                ignore=lambda directory, names: self.GENERATED.intersection(names) if Path(directory) == path.parent else set())
                document.update(workflow_id=str(uuid.uuid4()), workflow_name=target.name, active=False)
                write_document(staging / 'workflow.json', document)
                staging.rename(target)
            finally:
                if staging.exists():
                    shutil.rmtree(staging)
            return target / 'workflow.json'

    def import_json(self, source, name=None):
        document = read_document(Path(source))
        with self.locked():
            target = self.destination(name or document['workflow_name'])
            document.update(workflow_id=str(uuid.uuid4()), workflow_name=target.name, active=False)
            target.mkdir()
            try:
                write_document(target / 'workflow.json', document)
            except BaseException:
                shutil.rmtree(target)
                raise
            return target / 'workflow.json'
