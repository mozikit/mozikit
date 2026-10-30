"""Explicit, lossless replay of validated successful upstream results."""
from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import sys

from ._file_utils import atomic_write
from .runtime_paths import get_app_data_dir
from .workflow_editing import upstream_node_ids


def canonical(value):
    def check(item):
        if isinstance(item, dict):
            if not all(isinstance(key, str) for key in item):
                raise ValueError('快照对象的键必须是字符串')
            for child in item.values():
                check(child)
        elif isinstance(item, list):
            for child in item:
                check(child)
        elif item is not None and type(item) not in (str, int, float, bool):
            raise ValueError('输出不可无损恢复为 JSON')
    check(value)
    return json.dumps(value, sort_keys=True, ensure_ascii=False, allow_nan=False, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(canonical(value).encode('utf-8')).hexdigest()


def contains_credentials(value):
    if isinstance(value, dict):
        return any(any(word in str(key).lower() for word in ('api_key', 'password', 'secret', 'token'))
                   or contains_credentials(item) for key, item in value.items())
    if isinstance(value, (list, tuple)):
        return any(contains_credentials(item) for item in value)
    return isinstance(value, str) and '{{credential.' in value


def graph(executor):
    return sorted([edge.from_node, edge.from_port, edge.to_node, edge.to_port] for edge in executor.edges)


def environment(executor):
    directory = Path(executor.uv_manager.get_venv_path(executor.workflow_name))
    files = list(directory.glob('**/*.dist-info/METADATA')) if directory.exists() else []
    config = directory / 'pyvenv.cfg'
    return digest({'python': sys.version, 'venv': config.read_text(errors='replace') if config.exists() else None,
                   'packages': sorted((str(file.relative_to(directory)), hashlib.sha256(file.read_bytes()).hexdigest()) for file in files)})


def signature(node):
    from .node_registry import get_registry
    definition = get_registry().get_node(node.node_type)
    return digest({'type': str(node.node_type), 'version': node.version,
                   'config': node.config, 'source': node.source_code,
                   'definition_version': getattr(definition, 'version', None),
                   'dependencies': getattr(definition, 'dependencies', [])})


class ExecutionSnapshots:
    def __init__(self, directory=None):
        self.directory = Path(directory or get_app_data_dir() / 'execution-snapshots')

    def _path(self, run_id):
        if not isinstance(run_id, str) or not run_id or Path(run_id).name != run_id or '/' in run_id or '\\' in run_id or run_id in {'.', '..'}:
            raise ValueError('无效的运行 ID')
        return self.directory / (run_id + '.json')

    def save(self, executor, report):
        if not report.get('success') or report.get('stopped'):
            return
        executed = {node['node_id'] for node in report.get('nodes', []) if node.get('success')}
        outputs = {node_id: deepcopy(result['output']) for node_id, result in executor.node_results.items()
                   if node_id in executed and result['report'].get('success')}
        if contains_credentials(getattr(executor, '_run_initial_data', {})) or any(contains_credentials(node.config) for node in executor.nodes.values()):
            report['snapshot_unavailable'] = '含凭据配置的运行不支持复用'
            return
        document = {'version': 1, 'workflow_id': executor.workflow_id, 'graph': graph(executor),
                    'nodes': sorted(executor.nodes), 'initial': digest(getattr(executor, '_run_initial_data', {})),
                    'environment': environment(executor), 'outputs': outputs,
                    'signatures': {node_id: signature(node) for node_id, node in executor.nodes.items()},
                    'reports': {node_id: deepcopy(result['report']) for node_id, result in executor.node_results.items()
                                if node_id in outputs}, 'run_id': report['run_id']}
        artifacts = []
        def collect(value):
            if isinstance(value, dict):
                for key, item in value.items():
                    if key == 'artifacts' and isinstance(item, dict):
                        for path in item.values():
                            if isinstance(path, str) and Path(path).is_file():
                                artifacts.append({'path': str(Path(path).resolve()), 'sha256': hashlib.sha256(Path(path).read_bytes()).hexdigest()})
                    collect(item)
            elif isinstance(value, list):
                for item in value:
                    collect(item)
        collect(outputs)
        document['artifacts'] = artifacts
        payload = canonical(document)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if os.name != 'nt':
            self.directory.chmod(0o700)
        path = self._path(report['run_id'])
        atomic_write(path, payload)
        if os.name != 'nt':
            path.chmod(0o600)
        executor._last_run_id = report['run_id']

    def restore(self, executor, run_id, target, initial_data=None):
        if not target:
            raise ValueError('--reuse-run 必须与 --node 一起使用')
        try:
            stored = json.loads(self._path(run_id).read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError('运行快照不存在或无法恢复，未执行任何节点') from exc
        if not isinstance(stored, dict) or any(not isinstance(stored.get(key), dict) for key in ('signatures', 'outputs', 'reports')):
            raise ValueError('运行快照格式无效，未执行任何节点')
        artifacts = stored.get('artifacts', [])
        if not isinstance(artifacts, list) or any(not isinstance(item, dict) or not isinstance(item.get('path'), str) or not isinstance(item.get('sha256'), str) for item in artifacts):
            raise ValueError('运行快照产物格式无效，未执行任何节点')
        required = upstream_node_ids(target, executor.nodes, [(e.from_node, e.to_node) for e in executor.edges]) - {target}
        if stored.get('version') != 1 or stored.get('workflow_id') != executor.workflow_id:
            raise ValueError('快照工作流身份不兼容')
        if stored.get('graph') != graph(executor) or stored.get('nodes') != sorted(executor.nodes):
            raise ValueError('快照图结构不兼容')
        if stored.get('initial') != digest(initial_data or {}):
            raise ValueError('快照初始输入不兼容')
        if stored.get('environment') != environment(executor):
            raise ValueError('快照依赖环境不兼容')
        for node_id in required:
            node = executor.nodes[node_id]
            if contains_credentials(node.config) or stored.get('signatures', {}).get(node_id) != signature(node):
                raise ValueError(f'上游节点 {node_id} 的配置、源码或版本不兼容')
            if node_id not in stored['outputs'] or not isinstance(stored['reports'].get(node_id), dict) or not stored['reports'][node_id].get('success'):
                raise ValueError(f'上游节点 {node_id} 没有可恢复的成功输出')
        for artifact in stored.get('artifacts', []):
            path = Path(artifact['path'])
            if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != artifact['sha256']:
                raise ValueError('快照产物丢失或已变化')
        executor.node_results = {node_id: {'output': deepcopy(stored['outputs'][node_id]),
                                          'report': deepcopy(stored['reports'][node_id])} for node_id in required}
        executor._reuse_run_id = run_id
        return required
