"""Cross-process, three-way configuration updates, including explicit deletion."""
from copy import deepcopy
import json
from pathlib import Path
from threading import Lock

from filelock import FileLock

from ._file_utils import atomic_write

_locks = {}
_locks_guard = Lock()


def configuration_lock(path):
    key = str(Path(path).resolve())
    with _locks_guard:
        return _locks.setdefault(key, FileLock(key + '.lock', timeout=15))


def merge_changes(base, current, disk):
    if current == base:
        return deepcopy(disk)
    if all(isinstance(value, dict) for value in (base, current, disk)):
        result = deepcopy(disk)
        for key in base.keys() - current.keys():
            result.pop(key, None)
        for key, value in current.items():
            if key not in base:
                if key in disk and isinstance(value, dict) and isinstance(disk[key], dict):
                    result[key] = merge_changes({}, value, disk[key])
                elif key in disk and isinstance(value, list) and isinstance(disk[key], list):
                    result[key] = merge_changes([], value, disk[key])
                else:
                    result[key] = deepcopy(value)
            elif key not in disk:
                if value != base[key]:
                    result[key] = deepcopy(value)
            else:
                result[key] = merge_changes(base[key], value, disk[key])
        return result
    if all(isinstance(value, list) for value in (base, current, disk)):
        values = base + current + disk
        if values and all(isinstance(item, dict) and item.get("id") for item in values):
            old = {item['id']: item for item in base}
            now = {item['id']: item for item in current}
            stored = {item['id']: item for item in disk}
            merged = merge_changes(old, now, stored)
            # New records precede existing records; concurrent additions survive.
            order = [item['id'] for item in current if item['id'] not in old]
            order += [item['id'] for item in disk] + [item['id'] for item in current]
            return [merged.pop(key) for key in dict.fromkeys(order) if key in merged]
    return deepcopy(current)


def commit_config(path: Path, baseline: dict, current: dict) -> dict:
    path.parent.mkdir(parents=True, exist_ok=True)
    with configuration_lock(path):
        stored = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        if not isinstance(stored, dict):
            raise ValueError('configuration must be an object')
        merged = merge_changes(baseline, current, stored)
        if 'execution_history' in merged:
            merged['execution_history'] = merged['execution_history'][:500]
        atomic_write(path, json.dumps(merged, ensure_ascii=False, indent=2))
        return merged
