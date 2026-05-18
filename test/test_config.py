#!/usr/bin/env python3
"""
测试路径配置
"""
import os
import sys
from pathlib import Path

# 项目根目录
PROJECT_ROOT = Path(__file__).parent.parent

# 源代码目录
SRC_DIR = PROJECT_ROOT / "src"

# 测试目录
TEST_DIR = PROJECT_ROOT / "test"

# 单元测试目录
UNIT_TEST_DIR = TEST_DIR / "unit"

# 集成测试目录
INTEGRATION_TEST_DIR = TEST_DIR / "integration"

# UI测试目录
UI_TEST_DIR = TEST_DIR / "ui"

# 确保 src 目录在 Python 路径中
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# 确保项目根目录在 Python 路径中
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))