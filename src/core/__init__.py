# Core workflow execution components

import subprocess
import os
import re
import sys
from pathlib import Path

from .exceptions import ErrorCode, MozikitError


def resolve_workspace() -> Path:
    """Resolve workspace root – env MOZIKIT_WORKSPACE, else ./workflows."""
    env_ws = os.environ.get("MOZIKIT_WORKSPACE")
    if env_ws:
        return Path(env_ws)
    if getattr(sys, "frozen", False):
        from .runtime_paths import get_workspace_dir

        return get_workspace_dir()
    return Path("workflows")


def _get_version_from_git():
    """Return a version only when HEAD is exactly a release tag."""
    if getattr(sys, "frozen", False):
        return None
    try:
        result = subprocess.run(
            ["git", "describe", "--tags", "--exact-match", "--match", "v*"],
            capture_output=True,
            text=True,
            cwd=Path(__file__).parent.parent.parent,
        )
        if result.returncode == 0:
            version = result.stdout.strip()
            # 去掉 v 前缀（如果有）
            if version.startswith("v"):
                version = version[1:]
            if re.fullmatch(r"\d+\.\d+\.\d+(?:[-+][0-9A-Za-z.-]+)?", version):
                return version
    except Exception:
        pass
    return None


def _get_version_from_file():
    """从版本文件获取版本号（打包后的情况）"""
    candidates = [Path(__file__).parent / "_version.py"]
    if getattr(sys, "frozen", False):
        candidates.insert(0, Path(sys.executable).resolve().parent / "_version.py")
    for version_file in candidates:
        if not version_file.exists():
            continue
        try:
            with open(version_file, "r", encoding="utf-8") as f:
                for line in f:
                    if line.startswith("__version__"):
                        return line.split("=")[1].strip().strip('"\'')
        except OSError:
            pass
    return None


def _get_version_from_project():
    """Read the source distribution version without requiring Python 3.11."""
    project_file = Path(__file__).parent.parent.parent / "pyproject.toml"
    if not project_file.exists():
        return None
    try:
        match = re.search(
            r"^\s*version\s*=\s*[\"']([^\"']+)[\"']",
            project_file.read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        return match.group(1) if match else None
    except OSError:
        return None


def get_version():
    """获取版本号

    优先级：
    1. MOZIKIT_VERSION（Release CI 注入）
    2. 当前 HEAD 的精确 release tag（源码运行）
    3. _version.py（冻结产物）
    4. pyproject.toml（源码 checkout）
    5. 默认版本号
    """
    env_version = os.environ.get("MOZIKIT_VERSION", "").strip()
    if env_version:
        return env_version.lstrip("v")

    # Release tag is authoritative when running directly from a tagged checkout.
    git_version = _get_version_from_git()
    if git_version:
        return git_version

    # Generated version file is authoritative in a frozen distribution.
    file_version = _get_version_from_file()
    if file_version:
        return file_version

    project_version = _get_version_from_project()
    if project_version:
        return project_version

    return "0.0.0"


__version__ = get_version()
