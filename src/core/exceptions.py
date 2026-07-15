"""
Mozikit 统一异常体系

所有结构化异常继承自 MozikitError，携带 ErrorCode 枚举。
向后兼容：MozikitError 是 Exception 的子类，现有 except Exception 块透明兼容。
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional


class ErrorCode(str, Enum):
    """统一错误码枚举（所有模块共享）"""

    # ── 通用 ──
    UNKNOWN_ERROR = "UNKNOWN_ERROR"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    NOT_IMPLEMENTED = "NOT_IMPLEMENTED"

    # ── 配置 ──
    CONFIG_LOAD_FAILED = "CONFIG_LOAD_FAILED"
    CONFIG_VALIDATION_FAILED = "CONFIG_VALIDATION_FAILED"

    # ── 工作流 ──
    WORKFLOW_LOAD_FAILED = "WORKFLOW_LOAD_FAILED"
    WORKFLOW_EXECUTION_FAILED = "WORKFLOW_EXECUTION_FAILED"
    WORKFLOW_NOT_FOUND = "WORKFLOW_NOT_FOUND"
    WORKFLOW_EMPTY = "WORKFLOW_EMPTY"
    WORKFLOW_RUNNING = "WORKFLOW_RUNNING"
    WORKFLOW_NOT_RUNNING = "WORKFLOW_NOT_RUNNING"
    WORKFLOW_CYCLE_DETECTED = "WORKFLOW_CYCLE_DETECTED"

    # ── 节点 ──
    NODE_NOT_FOUND = "NODE_NOT_FOUND"
    NODE_ALREADY_EXISTS = "NODE_ALREADY_EXISTS"
    NODE_EXECUTION_FAILED = "NODE_EXECUTION_FAILED"
    NODE_VALIDATION_FAILED = "NODE_VALIDATION_FAILED"
    NODE_CREATION_FAILED = "NODE_CREATION_FAILED"
    SYNTAX_ERROR = "SYNTAX_ERROR"

    # ── 连接 ──
    CONNECTION_NOT_FOUND = "CONNECTION_NOT_FOUND"
    CONNECTION_ALREADY_EXISTS = "CONNECTION_ALREADY_EXISTS"
    PORT_NOT_FOUND = "PORT_NOT_FOUND"
    PORT_IN_USE = "PORT_IN_USE"

    # ── 参数校验 ──
    INVALID_PARAMETER = "INVALID_PARAMETER"
    INVALID_EXPRESSION = "INVALID_EXPRESSION"
    INVALID_DESCRIPTION = "INVALID_DESCRIPTION"
    INVALID_VALUE_TYPE = "INVALID_VALUE_TYPE"
    CONFIG_SCHEMA_MISMATCH = "CONFIG_SCHEMA_MISMATCH"

    # ── 权限 ──
    PERMISSION_DENIED = "PERMISSION_DENIED"

    # ── AI ──
    AI_CONFIG_INCOMPLETE = "AI_CONFIG_INCOMPLETE"
    AI_API_FAILED = "AI_API_FAILED"
    AI_CONNECTION_FAILED = "AI_CONNECTION_FAILED"
    AI_TIMEOUT = "AI_TIMEOUT"
    AI_INVALID_RESPONSE = "AI_INVALID_RESPONSE"
    AI_GENERATION_FAILED = "AI_GENERATION_FAILED"

    # ── 环境 ──
    ENVIRONMENT_ALREADY_EXISTS = "ENVIRONMENT_ALREADY_EXISTS"
    ENVIRONMENT_CREATION_FAILED = "ENVIRONMENT_CREATION_FAILED"
    ENVIRONMENT_NOT_FOUND = "ENVIRONMENT_NOT_FOUND"

    # ── 依赖 ──
    INSTALLATION_FAILED = "INSTALLATION_FAILED"
    NO_DEPENDENCIES = "NO_DEPENDENCIES"

    # ── 变量 ──
    VARIABLE_ALREADY_EXISTS = "VARIABLE_ALREADY_EXISTS"
    VARIABLE_NOT_FOUND = "VARIABLE_NOT_FOUND"

    # ── 网络 ──
    SEARCH_FAILED = "SEARCH_FAILED"
    NETWORK_ERROR = "NETWORK_ERROR"
    IMPORT_FAILED = "IMPORT_FAILED"

    # ── 定时任务 ──
    INVALID_CRON_EXPRESSION = "INVALID_CRON_EXPRESSION"
    SCHEDULE_TASK_NOT_FOUND = "SCHEDULE_TASK_NOT_FOUND"

    # ── 调试 ──
    BREAKPOINT_ALREADY_SET = "BREAKPOINT_ALREADY_SET"
    BREAKPOINT_NOT_FOUND = "BREAKPOINT_NOT_FOUND"
    NO_EXECUTION_LOG = "NO_EXECUTION_LOG"

    # ── 文件/IO ──
    FILE_NOT_FOUND = "FILE_NOT_FOUND"
    FILE_READ_FAILED = "FILE_READ_FAILED"
    FILE_WRITE_FAILED = "FILE_WRITE_FAILED"

    # ── 仓库 ──
    REPO_NODE_NOT_FOUND = "REPO_NODE_NOT_FOUND"
    REPO_VERSION_NOT_FOUND = "REPO_VERSION_NOT_FOUND"
    REPO_FETCH_FAILED = "REPO_FETCH_FAILED"

    # ── 安全 ──
    CODE_SAFETY_REJECTED = "CODE_SAFETY_REJECTED"

    # ── AI 聊天（兼容 ai_chat_service 原有错误码） ──
    NODE_TYPE_NOT_AVAILABLE = "NODE_TYPE_NOT_AVAILABLE"
    DUPLICATION_FAILED = "DUPLICATION_FAILED"
    TEMPLATE_GENERATION_FAILED = "TEMPLATE_GENERATION_FAILED"
    UNSUPPORTED_TRIGGER_TYPE = "UNSUPPORTED_TRIGGER_TYPE"
    WEBHOOK_ALREADY_EXISTS = "WEBHOOK_ALREADY_EXISTS"


class MozikitError(Exception):
    """Mozikit 所有结构化异常的基类。

    携带 ErrorCode 和可读消息，兼容现有 except Exception 捕获。
    """

    def __init__(
        self,
        code: ErrorCode,
        message: str = "",
        *,
        cause: Optional[BaseException] = None,
    ):
        self.code = code
        self.message = message or code.value
        if cause:
            super().__init__(f"[{code.value}] {self.message}")
            self.__cause__ = cause
        else:
            super().__init__(f"[{code.value}] {self.message}")

    def __str__(self) -> str:
        return self.message

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": False,
            "error_code": self.code.value,
            "error": self.message,
        }


# 向后兼容别名
LocalFlowError = MozikitError
