"""
测试共享 fixtures — CliRunner, 临时目录, 配置隔离等。
"""
import os
import shutil
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# 确保 src/ 可导入
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


@pytest.fixture
def cli_runner():
    """提供 Typer CliRunner 实例。"""
    from typer.testing import CliRunner
    return CliRunner()


@pytest.fixture
def tmp_project_dir():
    """创建临时项目目录，自动清理。"""
    tmp = Path(tempfile.mkdtemp(prefix="mozikit_test_"))
    yield tmp
    if tmp.exists():
        shutil.rmtree(tmp, ignore_errors=True)


@pytest.fixture
def isolated_config(tmp_project_dir):
    """在临时目录中创建隔离的 ConfigManager。"""
    from src.core.config_manager import ConfigManager
    config_file = tmp_project_dir / "config.json"
    mgr = ConfigManager(str(config_file))
    return mgr


@pytest.fixture
def mock_registry():
    """Mock 的节点注册表。"""
    registry = MagicMock()
    registry._user_data_dir = "/tmp/test_user_data"
    return registry


@pytest.fixture
def mcp_project(tmp_path):
    """An actual dependency-free workflow usable by both MCP transports."""
    import json
    import venv

    workspace = tmp_path / "workflows"
    workflow_dir = workspace / "demo"
    workflow_dir.mkdir(parents=True)
    (workflow_dir / "workflow.json").write_text(json.dumps({
        "version": 2, "workflow_name": "demo",
        "nodes": [{"node_id": "n1", "node_type": "custom_echo", "config": {}}], "edges": [],
    }))
    node_dir = tmp_path / "user_data/custom_nodes/custom_echo"
    node_dir.mkdir(parents=True)
    (node_dir / "node.json").write_text(json.dumps({
        "node_type": "custom_echo", "name": "Echo", "version": "1.0.0", "dependencies": [],
    }))
    (node_dir / "node.py").write_text(
        "def execute(self, input_data):\n"
        "    print('hello from node')\n"
        "    if input_data.get('fail'):\n"
        "        raise ValueError('requested failure')\n"
        "    return {**input_data, 'echo': '你好 MCP'}\n", encoding="utf-8"
    )
    venv.EnvBuilder(with_pip=False).create(workflow_dir / ".venv")
    env = {**os.environ, "PYTHONPATH": PROJECT_ROOT, "PYTHONIOENCODING": "utf-8"}
    return tmp_path, workspace, env
