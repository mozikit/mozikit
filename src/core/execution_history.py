"""Read persisted execution reports from the common history index."""
import json
from pathlib import Path


def read_report(record):
    artifact_dir = record.get("artifact_dir")
    if not artifact_dir:
        # Startup failures have an index entry but no executor artifacts.
        return record
    path = Path(artifact_dir) / "run.json"
    if not path.is_file():
        raise ValueError(f"执行报告不存在: {path}")
    return json.loads(path.read_text(encoding="utf-8"))
