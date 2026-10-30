"""The target of a schedule is a workflow, not its display label."""
from pathlib import Path

from .workflow_lifecycle import read_document


def validate_schedule_updates(updates: dict) -> dict:
    updates = dict(updates)
    if 'workflow_path' in updates:
        path = Path(updates['workflow_path']).expanduser().resolve()
        document = read_document(path)
        updates.update(workflow_path=str(path), workflow_name=document['workflow_name'])
    return updates
