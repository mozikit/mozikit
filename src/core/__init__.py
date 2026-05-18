# Core workflow execution components

import subprocess
import os
from pathlib import Path

from .exceptions import ErrorCode, LocalFlowError


def resolve_workspace() -> Path:
    """Resolve workspace root – env LOCALFLOW_WORKSPACE, else ./workflows."""
    env_ws = os.environ.get("LOCALFLOW_WORKSPACE")
    if env_ws:
        return Path(env_ws)
    return Path("workflows")


def _get_version_from_git():
    """从 git tag 获取版本号"""
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--always"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            # 去掉 v 前缀（如果有）
            if version.startswith("v"):
                version = version[1:]
            return version
    except Exception:
        pass
    return None


def _get_version_from_file():
    """从版本文件获取版本号（打包后的情况）"""
    version_file = Path(__file__).parent / "_version.py"
    if version_file.exists():
        try:
            with open(version_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("__version__"):
                        return line.split("=")[1].strip().strip('"\'')
        except Exception:
            pass
    return None


def get_version():
    """获取版本号

    优先级：
    1. 从 git tag 获取（开发环境）
    2. 从 _version.py 文件获取（打包后）
    3. 返回默认版本号
    """
    # 1. 尝试从 git 获取
    git_version = _get_version_from_git()
    if git_version:
        return git_version

    # 2. 尝试从版本文件获取
    file_version = _get_version_from_file()
    if file_version:
        return file_version

    # 3. 默认版本号
    return "0.0.0"


__version__ = get_version()
