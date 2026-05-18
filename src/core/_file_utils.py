"""
原子文件写入工具 — 先写临时文件再重命名，防止写入中断导致文件损坏。
"""
import json
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

from src.core.log_manager import get_logger

logger = get_logger("_file_utils")


def atomic_write(path: Path | str, content: str | bytes) -> None:
    """原子写入：写临时文件 → os.replace 替换目标文件。

    文本模式写入 str，二进制模式写入 bytes。
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = "w" if isinstance(content, str) else "wb"
    encoding = "utf-8" if isinstance(content, str) else None
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with open(fd, mode, encoding=encoding) as f:
            f.write(content)
        os.replace(tmp, str(path))
    except Exception:
        try:
            os.unlink(tmp)
        except Exception:
            pass
        raise


def atomic_write_json(path: Path | str, data: Any) -> None:
    """异步（后台线程）原子 JSON 写入。"""
    def _do():
        try:
            atomic_write_json_sync(path, data)
        except Exception as e:
            logger.error("atomic_write_json failed: %s", e)
    threading.Thread(target=_do, daemon=True).start()


def atomic_write_json_sync(path: Path | str, data: Any) -> None:
    """同步原子 JSON 写入 — 先读已有内容合并后再写。"""
    path = Path(path)
    existing = {}
    if path.exists():
        try:
            with open(path, "r", encoding="utf-8") as f:
                existing = json.load(f)
        except Exception:
            existing = {}
    merged = existing.copy()
    if isinstance(data, dict):
        merged.update(data)
    else:
        merged = data
    content = json.dumps(merged, ensure_ascii=False, indent=2)
    atomic_write(path, content)
