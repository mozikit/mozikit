"""
AI 聊天服务
基于 OpenAI 兼容接口的 Function Calling 实现工作流 Agent
"""

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

from enum import Enum

from src.core.ai_chat_context import AIChatContextBuilder
from src.core.log_manager import get_logger


class ErrorCode(str, Enum):
    NODE_NOT_FOUND = "NODE_NOT_FOUND"
    INVALID_PARAMETER = "INVALID_PARAMETER"
    PORT_NOT_FOUND = "PORT_NOT_FOUND"
    CONNECTION_NOT_FOUND = "CONNECTION_NOT_FOUND"
    CONNECTION_ALREADY_EXISTS = "CONNECTION_ALREADY_EXISTS"
    WORKFLOW_EMPTY = "WORKFLOW_EMPTY"
    WORKFLOW_RUNNING = "WORKFLOW_RUNNING"
    CONFIG_SCHEMA_MISMATCH = "CONFIG_SCHEMA_MISMATCH"
    PERMISSION_DENIED = "PERMISSION_DENIED"
    INTERNAL_ERROR = "INTERNAL_ERROR"
    # 高优先级
    WORKFLOW_NOT_RUNNING = "WORKFLOW_NOT_RUNNING"
    NO_EXECUTION_LOG = "NO_EXECUTION_LOG"
    TEMPLATE_GENERATION_FAILED = "TEMPLATE_GENERATION_FAILED"
    INVALID_DESCRIPTION = "INVALID_DESCRIPTION"
    ENVIRONMENT_ALREADY_EXISTS = "ENVIRONMENT_ALREADY_EXISTS"
    ENVIRONMENT_CREATION_FAILED = "ENVIRONMENT_CREATION_FAILED"
    NO_DEPENDENCIES = "NO_DEPENDENCIES"
    INSTALLATION_FAILED = "INSTALLATION_FAILED"
    # 中优先级
    VARIABLE_ALREADY_EXISTS = "VARIABLE_ALREADY_EXISTS"
    VARIABLE_NOT_FOUND = "VARIABLE_NOT_FOUND"
    INVALID_VALUE_TYPE = "INVALID_VALUE_TYPE"
    SEARCH_FAILED = "SEARCH_FAILED"
    NETWORK_ERROR = "NETWORK_ERROR"
    NODE_NOT_FOUND_IN_COMMUNITY = "NODE_NOT_FOUND_IN_COMMUNITY"
    IMPORT_FAILED = "IMPORT_FAILED"
    NODE_ALREADY_EXISTS = "NODE_ALREADY_EXISTS"
    NODE_TYPE_NOT_AVAILABLE = "NODE_TYPE_NOT_AVAILABLE"
    INVALID_EXPRESSION = "INVALID_EXPRESSION"
    NOT_A_CONDITION_NODE = "NOT_A_CONDITION_NODE"
    # 低优先级
    UNSUPPORTED_TRIGGER_TYPE = "UNSUPPORTED_TRIGGER_TYPE"
    INVALID_TRIGGER_CONFIG = "INVALID_TRIGGER_CONFIG"
    WEBHOOK_ALREADY_EXISTS = "WEBHOOK_ALREADY_EXISTS"
    PORT_IN_USE = "PORT_IN_USE"
    EXECUTION_FAILED = "EXECUTION_FAILED"
    BREAKPOINT_ALREADY_SET = "BREAKPOINT_ALREADY_SET"
    BREAKPOINT_NOT_FOUND = "BREAKPOINT_NOT_FOUND"
    DUPLICATION_FAILED = "DUPLICATION_FAILED"


def _error_result(error_code: ErrorCode, error: str, detail: dict = None) -> dict:
    result = {"success": False, "error_code": error_code.value, "error": error}
    if detail:
        result["detail"] = detail
    return result


class AIChatError(Exception):
    """AI 聊天异常"""


logger = get_logger("ai_chat_service")


class AIChatService:
    """AI 聊天服务 — 基于 OpenAI 兼容接口的 Function Calling"""

    DEFAULT_MAX_HISTORY_ROUNDS = 20
    MAX_TOOL_ROUNDS = 10
    HISTORY_FILE = Path("user_data") / "chat_history.json"

    def __init__(self, ai_settings: dict, max_history_rounds: int = None):
        self.ai_settings = ai_settings or {}
        self.max_history_rounds = max_history_rounds or self.DEFAULT_MAX_HISTORY_ROUNDS
        self.messages: List[dict] = []
        self.tool_definitions = self._build_tool_definitions()
        self._load_history()

    def chat(
        self,
        user_message: str,
        workflow_context: dict,
        tool_executor=None,
        stream_callback=None,
    ) -> dict:
        """
        一次完整的对话轮次

        Args:
            user_message: 用户消息
            workflow_context: 工作流上下文 (build_context 返回值)
            tool_executor: AIToolExecutor 实例，用于执行工具
            stream_callback: 流式回调函数，签名 callback(chunk_text: str)

        Returns:
            dict: {"reply": str, "tool_results": list}
        """
        self._validate_settings()

        system_prompt = self._build_system_prompt(workflow_context)

        system_msg = {"role": "system", "content": system_prompt}
        self.messages.append({"role": "user", "content": user_message})

        max_messages = self.max_history_rounds * 2
        recent_messages = self.messages[-max_messages:]
        all_messages = [system_msg] + self._summarize_messages(
            recent_messages, max_messages
        )

        tool_results = []
        final_reply = ""
        executed_tool_signatures = set()

        try:
            use_tools = tool_executor is not None

            for _round in range(self.MAX_TOOL_ROUNDS):
                response_data = self._call_llm(
                    all_messages, use_tools=use_tools, stream_callback=stream_callback
                )
                message = self._normalize_assistant_message(
                    response_data["choices"][0]["message"]
                )

                # 处理标准 OpenAI Function Calling 格式
                if not message.get("tool_calls"):
                    content = message.get("content", "")
                    final_reply = content
                    break

                tool_calls = message["tool_calls"]
                tool_call_signatures = [
                    self._tool_call_signature(tool_call) for tool_call in tool_calls
                ]
                if all(sig in executed_tool_signatures for sig in tool_call_signatures):
                    logger.warning("检测到重复工具调用，终止本轮工具循环: %s", tool_call_signatures)
                    final_reply = "操作已经执行过，已停止重复调用工具。"
                    break

                all_messages.append(message)
                self.messages.append(message)

                for tool_call, signature in zip(tool_calls, tool_call_signatures):
                    tool_name = tool_call["function"]["name"]
                    arguments = self._parse_tool_arguments(
                        tool_call["function"].get("arguments")
                    )

                    result = {
                        "tool_call_id": tool_call.get("id", ""),
                        "tool_name": tool_name,
                        "arguments": arguments,
                        "result": None,
                        "success": False,
                    }

                    if signature in executed_tool_signatures:
                        logger.warning("跳过重复工具调用: %s", signature)
                        result["result"] = _error_result(
                            ErrorCode.INVALID_PARAMETER, "重复工具调用，已跳过"
                        )
                    elif tool_executor:
                        executed_tool_signatures.add(signature)
                        try:
                            exec_result = tool_executor.execute(tool_name, arguments)
                            result["result"] = exec_result
                            result["success"] = exec_result.get("success", False)
                        except Exception as exc:
                            result["result"] = _error_result(
                                ErrorCode.INTERNAL_ERROR, str(exc)
                            )
                            logger.error("工具执行失败 %s: %s", tool_name, exc)

                    tool_results.append(result)

                    # 构建 tool 消息，content 使用字符串格式
                    # 避免复杂的 JSON 结构，使用简单的字符串表示
                    result_content = result["result"]
                    if isinstance(result_content, dict):
                        # 如果是字典，提取关键信息作为字符串
                        if result_content.get("success"):
                            content_str = (
                                f"执行成功: {result_content.get('message', '完成')}"
                            )
                        else:
                            content_str = (
                                f"执行失败: {result_content.get('error', '未知错误')}"
                            )
                    else:
                        content_str = (
                            str(result_content) if result_content else "执行完成"
                        )

                    tool_msg = {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id", ""),
                        "content": content_str,
                    }
                    all_messages.append(tool_msg)
                    self.messages.append(tool_msg)
            else:
                logger.warning(
                    "工具调用达到最大轮次 %d，强制终止", self.MAX_TOOL_ROUNDS
                )
                if not final_reply:
                    final_reply = "工具调用轮次已达上限，操作可能未全部完成。"

            self.messages.append({"role": "assistant", "content": final_reply})

        except AIChatError:
            raise
        except Exception as exc:
            logger.error("AI 聊天调用异常: %s", exc)
            raise AIChatError(f"AI 调用失败: {exc}") from exc

        self._save_history()
        return {"reply": final_reply, "tool_results": tool_results}

    def clear_history(self):
        """清空对话历史"""
        self.messages.clear()
        self._save_history()

    def export_history(self) -> str:
        """导出格式化的对话历史文本"""
        if not self.messages:
            return "(无对话记录)"

        role_labels = {
            "user": "用户",
            "assistant": "AI",
            "system": "系统",
            "tool": "工具",
        }
        lines = []
        for i, msg in enumerate(self.messages, 1):
            role = msg.get("role", "unknown")
            label = role_labels.get(role, role)
            content = msg.get("content", "")
            if role == "tool":
                content = f"[工具结果] {content[:200]}"
            lines.append(f"[{i}] {label}: {content}")
        return "\n".join(lines)

    def _load_history(self):
        """启动时从文件加载对话历史"""
        try:
            history_file = self.HISTORY_FILE
            if history_file.exists():
                with open(history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self.messages = data if isinstance(data, list) else []
                # 清理历史消息中的格式问题
                self._sanitize_history_messages()
                logger.info("加载对话历史: %d 条消息", len(self.messages))
        except Exception as exc:
            logger.warning("加载对话历史失败: %s", exc)
            self.messages = []

    def _sanitize_history_messages(self):
        """清理历史消息中的格式问题"""
        cleaned_messages = []
        for msg in self.messages:
            if not isinstance(msg, dict):
                continue
            role = msg.get("role")
            # 检查 tool 消息的格式
            if role == "tool":
                # 确保 tool 消息有 tool_call_id 和 content
                if not msg.get("tool_call_id"):
                    logger.warning(
                        "历史消息中 tool 消息缺少 tool_call_id，跳过: %s", msg
                    )
                    continue
                if not msg.get("content"):
                    msg["content"] = "执行完成"
                cleaned_messages.append(msg)
            elif role in ("user", "assistant", "system"):
                # 确保 assistant 消息的 tool_calls 格式正确
                if role == "assistant" and msg.get("tool_calls"):
                    valid_tool_calls = self._normalize_tool_calls(msg["tool_calls"])
                    if valid_tool_calls:
                        msg["tool_calls"] = valid_tool_calls
                    else:
                        msg.pop("tool_calls", None)
                cleaned_messages.append(msg)
            else:
                # 跳过未知角色的消息
                logger.warning("历史消息中未知角色: %s", role)
        self.messages = cleaned_messages

    def _save_history(self):
        """将对话历史保存到文件（异步，不阻塞调用线程）"""
        try:
            messages_copy = list(self.messages)
            history_file = self.HISTORY_FILE
            import threading

            def _do_save():
                try:
                    history_file.parent.mkdir(parents=True, exist_ok=True)
                    with open(history_file, "w", encoding="utf-8") as f:
                        json.dump(messages_copy, f, ensure_ascii=False, indent=2)
                except Exception as exc:
                    logger.warning("保存对话历史失败: %s", exc)

            threading.Thread(target=_do_save, daemon=True).start()
        except Exception as exc:
            logger.warning("启动保存对话历史线程失败: %s", exc)

    @classmethod
    def _normalize_messages_for_api(cls, messages: list) -> list:
        """返回可安全发送给 OpenAI 兼容接口的消息副本。"""
        normalized_messages = []
        pending_tool_call_ids = set()
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            normalized = dict(msg)
            role = normalized.get("role")
            if role == "assistant":
                pending_tool_call_ids.clear()
            if role == "assistant" and normalized.get("tool_calls"):
                tool_calls = cls._normalize_tool_calls(normalized["tool_calls"])
                if tool_calls:
                    normalized["tool_calls"] = tool_calls
                    pending_tool_call_ids.update(
                        tc["id"] for tc in tool_calls if tc.get("id")
                    )
                else:
                    normalized.pop("tool_calls", None)
            elif role == "tool":
                tool_call_id = normalized.get("tool_call_id")
                if tool_call_id not in pending_tool_call_ids:
                    logger.warning("跳过无匹配 assistant tool_call 的 tool 消息: %s", msg)
                    continue
                if not normalized.get("content"):
                    normalized["content"] = "执行完成"
            normalized_messages.append(normalized)
        return normalized_messages

    @classmethod
    def _normalize_assistant_message(cls, message: dict) -> dict:
        """规范化模型返回的 assistant 消息，确保 tool arguments 是 JSON 字符串。"""
        if not isinstance(message, dict):
            return {"role": "assistant", "content": ""}
        normalized = dict(message)
        if normalized.get("tool_calls"):
            tool_calls = cls._normalize_tool_calls(normalized["tool_calls"])
            if tool_calls:
                normalized["tool_calls"] = tool_calls
            else:
                normalized.pop("tool_calls", None)
        return normalized

    @classmethod
    def _normalize_tool_calls(cls, tool_calls: list) -> list:
        """将 tool_calls 规范化为 API 可接受的格式。"""
        normalized_tool_calls = []
        for tool_call in tool_calls:
            if not isinstance(tool_call, dict):
                logger.warning("无效的 tool_call，已跳过: %s", tool_call)
                continue

            function = tool_call.get("function")
            if not isinstance(function, dict) or not function.get("name"):
                logger.warning("tool_call 缺少 function.name，已跳过: %s", tool_call)
                continue
            tool_call_id = tool_call.get("id", "")
            if not tool_call_id:
                logger.warning("tool_call 缺少 id，已跳过: %s", tool_call)
                continue

            arguments = cls._parse_tool_arguments(function.get("arguments"))
            normalized_tool_calls.append(
                {
                    "id": tool_call_id,
                    "type": tool_call.get("type", "function"),
                    "function": {
                        "name": function["name"],
                        "arguments": json.dumps(
                            arguments, ensure_ascii=False, separators=(",", ":")
                        ),
                    },
                }
            )
        return normalized_tool_calls

    @staticmethod
    def _parse_tool_arguments(raw_arguments: Any) -> dict:
        """解析 function.arguments；非法或非对象参数按空对象处理。"""
        if raw_arguments in (None, ""):
            return {}
        if isinstance(raw_arguments, dict):
            return raw_arguments
        if isinstance(raw_arguments, str):
            try:
                parsed = json.loads(raw_arguments)
            except json.JSONDecodeError:
                logger.warning(
                    "模型返回了非法的 function.arguments JSON，已按空对象处理: %r",
                    raw_arguments,
                )
                return {}
            if isinstance(parsed, dict):
                return parsed
            logger.warning(
                "模型返回的 function.arguments 不是 JSON 对象，已按空对象处理: %r",
                raw_arguments,
            )
            return {}
        logger.warning(
            "模型返回的 function.arguments 类型无效，已按空对象处理: %s",
            type(raw_arguments).__name__,
        )
        return {}

    @classmethod
    def _tool_call_signature(cls, tool_call: dict) -> tuple:
        """生成工具调用签名，用于防止同一轮对话重复执行相同操作。"""
        function = tool_call.get("function", {}) if isinstance(tool_call, dict) else {}
        name = function.get("name", "") if isinstance(function, dict) else ""
        arguments = cls._parse_tool_arguments(function.get("arguments"))
        return (
            name,
            json.dumps(arguments, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
        )

    def _summarize_messages(self, messages: list, max_messages: int) -> list:
        """对话摘要：当消息超过上限时，保留首尾，中间用摘要占位"""
        if len(messages) <= max_messages:
            return messages

        keep_head = min(4, len(messages))
        keep_tail = min(max_messages - keep_head - 1, len(messages) - keep_head)
        omitted = len(messages) - keep_head - keep_tail

        summary_msg = {"role": "system", "content": f"[已省略 {omitted} 条早期对话]"}
        return messages[:keep_head] + [summary_msg] + messages[-keep_tail:]

    def _validate_settings(self):
        """校验 AI 配置"""
        missing = [
            field
            for field in ("base_url", "api_key", "model")
            if not str(self.ai_settings.get(field, "")).strip()
        ]
        if missing:
            raise AIChatError(f"AI 配置不完整，缺少: {', '.join(missing)}")

    def _build_system_prompt(self, workflow_context: dict) -> str:
        """构建系统提示词"""
        context_text = AIChatContextBuilder.build_system_prompt_text(workflow_context)
        available_types = workflow_context.get("available_node_types", [])

        return (
            "你是 LocalFlow 的 AI 助手，专门帮助用户组织和管理工作流节点。\n\n"
            "## 你的能力\n"
            "你可以通过工具调用直接操作工作流画布：\n"
            "- **节点操作**: add_node, delete_node, connect_nodes, disconnect_nodes, update_node_config\n"
            "- **信息查询**: get_workflow_info, get_node_detail, list_workflows\n"
            "- **工作流管理**: arrange_nodes, run_workflow, save_workflow\n"
            "- **调试诊断**: get_execution_status, get_execution_log, debug_node, set_breakpoint, remove_breakpoint\n"
            "- **脚手架**: generate_workflow_template\n"
            "- **环境管理**: create_workflow_environment, install_node_dependencies\n"
            "- **变量管理**: set_workflow_variable, get_workflow_variable, list_workflow_variables\n"
            "- **节点市场**: search_community_nodes, import_community_node\n"
            "- **条件控制**: add_condition_node, configure_condition\n"
            "- **触发器**: configure_trigger, expose_webhook\n"
            "- **画布增强**: duplicate_node_group, enable_node\n\n"
            "## 当前工作流上下文\n"
            f"{context_text}\n\n"
            "## 工作原则\n"
            "1. 理解用户意图后，优先使用工具执行操作，而不是仅提供建议\n"
            "2. 添加节点时，合理推断位置（避免与现有节点重叠），优先放在空白区域\n"
            "3. 连接节点时，检查数据流逻辑，避免循环依赖\n"
            "4. 修改配置前，先确认节点存在；需要了解节点详细配置或端口连接时，使用 get_node_detail 工具\n"
            "5. 删除操作需谨慎：调用 delete_node 时会返回确认请求，你必须将确认信息展示给用户；仅当用户明确确认删除后，才可调用 confirm_delete_node 执行真正删除\n"
            "6. 对于模糊请求（如'帮我建一个查询数据库的流程'），主动选择合适的节点组合并连接\n"
            "7. 使用中文回复\n"
            "8. 当用户要求运行/执行工作流时，使用 run_workflow 工具触发执行；如果工作流已在执行中，告知用户等待\n"
            "9. 当用户要求保存工作流时，使用 save_workflow 工具保存当前画布内容\n"
            "10. 当用户想知道有哪些工作流可用时，使用 list_workflows 工具列出所有已保存的工作流名称\n"
            "11. 工作流脚手架：generate_workflow_template 支持关键词'rss'、'数据库'、'爬虫'、'定时'等\n"
            '12. 变量管理：set_workflow_variable 值需为 JSON 字符串格式，如 \'{"key": "value"}\'\n'
            "13. 条件节点：add_condition_node 创建后需用 configure_condition 配置表达式\n"
            "14. 调试节点：debug_node 用于单独测试节点，不需要连接上游\n\n"
            "## 错误码说明\n"
            "工具执行失败时，返回结果中包含 error_code 字段，你可以根据 error_code 做差异化处理：\n"
            "- NODE_NOT_FOUND: 节点不存在，可提示用户先添加节点或用 get_workflow_info 查询有效节点\n"
            "- INVALID_PARAMETER: 参数不合法，需修正参数后重试\n"
            "- PORT_NOT_FOUND: 端口不存在，可用 get_node_detail 查询有效端口\n"
            "- CONNECTION_NOT_FOUND: 连接不存在，可提示用户节点间无连接\n"
            "- CONNECTION_ALREADY_EXISTS: 连接已存在，无需重复连接\n"
            "- WORKFLOW_EMPTY: 工作流为空，需先添加节点\n"
            "- WORKFLOW_RUNNING: 工作流正在执行中，需等待完成\n"
            "- CONFIG_SCHEMA_MISMATCH: 配置schema不匹配，可用 get_node_detail 查询 config_schema\n"
            "- PERMISSION_DENIED: 权限不足，需提示用户检查权限\n"
            "- INTERNAL_ERROR: 内部错误，可建议用户重试或检查工作流状态\n"
            "- WORKFLOW_NOT_RUNNING: 工作流尚未执行过\n"
            "- NO_EXECUTION_LOG: 暂无执行记录\n"
            "- TEMPLATE_GENERATION_FAILED: 模板生成失败\n"
            "- INVALID_DESCRIPTION: 描述无效\n"
            "- ENVIRONMENT_ALREADY_EXISTS: 虚拟环境已存在\n"
            "- ENVIRONMENT_CREATION_FAILED: 虚拟环境创建失败\n"
            "- NO_DEPENDENCIES: 节点无依赖\n"
            "- INSTALLATION_FAILED: 依赖安装失败\n"
            "- VARIABLE_ALREADY_EXISTS: 变量已存在\n"
            "- VARIABLE_NOT_FOUND: 变量不存在\n"
            "- INVALID_VALUE_TYPE: 变量值类型无效\n"
            "- SEARCH_FAILED: 社区节点搜索失败\n"
            "- NETWORK_ERROR: 网络错误\n"
            "- NODE_NOT_FOUND_IN_COMMUNITY: 社区中未找到该节点\n"
            "- IMPORT_FAILED: 节点导入失败\n"
            "- NODE_ALREADY_EXISTS: 节点已存在\n"
            "- NODE_TYPE_NOT_AVAILABLE: 节点类型不可用\n"
            "- INVALID_EXPRESSION: 表达式语法错误\n"
            "- NOT_A_CONDITION_NODE: 不是条件节点\n"
            "- UNSUPPORTED_TRIGGER_TYPE: 不支持的触发类型\n"
            "- INVALID_TRIGGER_CONFIG: 触发器配置无效\n"
            "- WEBHOOK_ALREADY_EXISTS: Webhook 已存在\n"
            "- PORT_IN_USE: 端口被占用\n"
            "- EXECUTION_FAILED: 执行失败\n"
            "- BREAKPOINT_ALREADY_SET: 断点已设置\n"
            "- BREAKPOINT_NOT_FOUND: 断点不存在\n"
            "- DUPLICATION_FAILED: 复制失败\n\n"
            f"## 可用节点类型\n{', '.join(available_types)}\n"
        )

    def _call_llm(
        self, messages: list, use_tools: bool = True, stream_callback=None
    ) -> dict:
        """
        调用 OpenAI 兼容接口

        Args:
            messages: 消息列表
            use_tools: 是否启用工具
            stream_callback: 流式回调函数，签名 callback(chunk_text: str)，
                             为 None 时使用非流式模式

        Returns:
            dict: OpenAI 兼容格式的完整响应（流式时由 chunks 拼装）
        """
        endpoint = self._build_endpoint(self.ai_settings["base_url"])

        payload = {
            "model": self.ai_settings["model"],
            "temperature": float(self.ai_settings.get("temperature", 0.3)),
            "messages": self._normalize_messages_for_api(messages),
        }
        # 检查是否禁用工具（某些API端点不支持function calling）
        tools_enabled = self.ai_settings.get("tools_enabled", True)
        if use_tools and tools_enabled and self.tool_definitions:
            payload["tools"] = self.tool_definitions
            payload["tool_choice"] = "auto"

        headers = {
            "Content-Type": "application/json; charset=utf-8",
            "Authorization": f"Bearer {self.ai_settings['api_key']}",
        }
        timeout = int(self.ai_settings.get("timeout_seconds", 60) or 60)

        # 修复：确保所有消息的 content 不为空（某些 API 要求）
        for i, msg in enumerate(payload.get("messages", [])):
            if not msg.get("content") and msg.get("role") != "tool":
                logger.debug("消息 %d content 为空，设置为空格", i)
                msg["content"] = " "

        # 调试：记录消息列表中的 tool 消息
        for i, msg in enumerate(payload.get("messages", [])):
            if msg.get("role") == "tool":
                logger.debug(
                    "Tool 消息 %d: tool_call_id=%s, content=%s",
                    i,
                    msg.get("tool_call_id"),
                    msg.get("content", "")[:100],
                )
            elif msg.get("role") == "assistant" and msg.get("tool_calls"):
                tc_ids = [tc.get("id") for tc in msg.get("tool_calls", [])]
                logger.debug("Assistant 消息 %d 包含 tool_calls: %s", i, tc_ids)

        use_stream = stream_callback is not None
        if use_stream:
            payload["stream"] = True

        try:
            if use_stream:
                # 添加调试日志，查看实际发送的请求
                logger.debug(
                    "流式请求 payload: %s",
                    json.dumps(payload, ensure_ascii=False, indent=2),
                )
                result = self._call_llm_stream(
                    endpoint, headers, payload, timeout, stream_callback
                )
                if result is not None:
                    return result
                logger.info("流式请求失败，自动 fallback 到非流式模式")
                payload.pop("stream", None)

            # 检查消息列表中是否有空 content（非 tool 消息）
            for i, msg in enumerate(payload.get("messages", [])):
                if not msg.get("content") and msg.get("role") != "tool":
                    logger.warning("消息 %d content 为空或缺失: %s", i, msg)
                    # 确保 content 不为空
                    msg["content"] = " "

            logger.debug(
                "非流式请求 payload: %s",
                json.dumps(payload, ensure_ascii=False, indent=2),
            )

            # 确保 payload 不为空
            if not payload or not payload.get("messages"):
                logger.error("payload 为空或消息列表为空: %s", payload)
                raise AIChatError("请求体为空，无法发送请求")

            return self._call_llm_non_stream(endpoint, headers, payload, timeout)
        except requests.exceptions.HTTPError as exc:
            error_body = ""
            if exc.response is not None:
                try:
                    error_body = exc.response.text
                    # 记录详细的错误信息以便调试
                    logger.error(
                        "HTTP 错误详情: status=%s, body=%s",
                        exc.response.status_code,
                        error_body,
                    )
                except Exception:
                    pass
            msg = error_body or str(exc)
            code = exc.response.status_code if exc.response is not None else 0
            raise AIChatError(f"AI 接口调用失败: HTTP {code} {msg}") from exc
        except requests.exceptions.ConnectionError as exc:
            raise AIChatError(f"AI 接口连接失败: {exc}") from exc
        except requests.exceptions.Timeout as exc:
            raise AIChatError(f"AI 接口请求超时: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise AIChatError("AI 接口返回了无法解析的 JSON") from exc

    def _call_llm_stream(
        self, endpoint: str, headers: dict, payload: dict, timeout: int, stream_callback
    ) -> Optional[dict]:
        """
        流式调用 LLM，解析 SSE 响应，返回拼装的完整响应 dict。
        若流式请求本身失败（如 API 不支持 stream），返回 None 以触发 fallback。
        """
        try:
            resp = requests.post(
                endpoint,
                json=payload,
                headers=headers,
                timeout=(10, timeout),
                stream=True,
            )
            resp.raise_for_status()
        except requests.exceptions.HTTPError as exc:
            if exc.response is not None and exc.response.status_code == 429:
                logger.warning("流式请求触发限流，停止本轮请求: %s", exc)
                raise
            logger.warning("流式请求建立失败: %s", exc)
            return None
        except Exception as exc:
            logger.warning("流式请求建立失败: %s", exc)
            return None

        content_parts = []
        tool_calls_map = {}
        finish_reason = None
        model_name = payload.get("model", "")

        # 显式设置编码为 UTF-8，避免某些 API provider 的编码猜测错误导致中文乱码
        resp.encoding = "utf-8"

        try:
            for line in resp.iter_lines(decode_unicode=True):
                if not line or not line.startswith("data: "):
                    continue
                data_str = line[6:]
                if data_str.strip() == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                except json.JSONDecodeError:
                    continue

                choices = chunk.get("choices", [])
                if not choices:
                    continue
                delta = choices[0].get("delta", {})
                fr = choices[0].get("finish_reason")
                if fr:
                    finish_reason = fr

                delta_content = delta.get("content")
                if delta_content:
                    content_parts.append(delta_content)
                    try:
                        stream_callback(delta_content)
                    except Exception:
                        pass

                delta_tool_calls = delta.get("tool_calls")
                if delta_tool_calls:
                    for dtc in delta_tool_calls:
                        self._merge_stream_tool_call(tool_calls_map, dtc)
        except Exception as exc:
            logger.warning("流式响应解析异常: %s", exc)
            resp.close()
            return None
        finally:
            resp.close()

        message = {"role": "assistant", "content": "".join(content_parts)}
        if tool_calls_map:
            sorted_tc = sorted(
                tool_calls_map.values(), key=lambda x: x.get("_index", 0)
            )
            sorted_tc = [tc for tc in sorted_tc if tc.get("function", {}).get("name")]
            if not sorted_tc:
                logger.warning("流式响应包含 tool_calls，但未解析到 function.name，回退非流式")
                return None
            for tc in sorted_tc:
                tc.pop("_index", None)
            message["tool_calls"] = sorted_tc
        if finish_reason:
            pass

        return {
            "choices": [{"message": message, "finish_reason": finish_reason or "stop"}],
            "model": model_name,
        }

    @staticmethod
    def _merge_stream_tool_call(tool_calls_map: dict, delta_tool_call: dict):
        """按 index 合并流式 tool_call 增量。"""
        if not isinstance(delta_tool_call, dict):
            return

        tc_idx = delta_tool_call.get("index", 0)
        key = str(tc_idx)
        tc_id = delta_tool_call.get("id")

        if key not in tool_calls_map:
            tool_calls_map[key] = {
                "id": tc_id or f"tc_{tc_idx}",
                "type": delta_tool_call.get("type", "function"),
                "function": {"name": "", "arguments": ""},
                "_index": tc_idx,
            }
        elif tc_id:
            tool_calls_map[key]["id"] = tc_id

        function_delta = delta_tool_call.get("function", {})
        if not isinstance(function_delta, dict):
            function_delta = {}

        name_delta = function_delta.get("name") or delta_tool_call.get("name")
        if name_delta:
            current_name = tool_calls_map[key]["function"]["name"]
            if not current_name:
                tool_calls_map[key]["function"]["name"] = name_delta
            elif not current_name.endswith(name_delta):
                tool_calls_map[key]["function"]["name"] += name_delta

        arguments_delta = function_delta.get("arguments")
        if arguments_delta:
            tool_calls_map[key]["function"]["arguments"] += arguments_delta

    def _call_llm_non_stream(
        self, endpoint: str, headers: dict, payload: dict, timeout: int
    ) -> dict:
        """非流式调用 LLM"""
        resp = requests.post(
            endpoint,
            json=payload,
            headers=headers,
            timeout=timeout,
        )
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _build_endpoint(base_url: str) -> str:
        """构建 API 端点"""
        normalized = base_url.rstrip("/")
        if normalized.endswith("/chat/completions"):
            return normalized
        if normalized.endswith("/v1"):
            return f"{normalized}/chat/completions"
        return f"{normalized}/v1/chat/completions"

    @staticmethod
    def _get_all_node_types() -> list:
        """动态获取所有可用节点类型列表（从注册表获取）"""
        try:
            from src.core.node_registry import get_registry

            registry = get_registry()
            return registry.list_node_types()
        except Exception:
            return []

    @staticmethod
    def _build_tool_definitions() -> list:
        """构建 Function Calling 工具定义"""
        node_type_list = AIChatService._get_all_node_types()
        node_type_desc = "节点类型标识，可用类型: " + ", ".join(node_type_list)

        return [
            {
                "type": "function",
                "function": {
                    "name": "add_node",
                    "description": "在工作流画布上添加一个节点",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "node_type": {
                                "type": "string",
                                "description": node_type_desc,
                            },
                            "title": {
                                "type": "string",
                                "description": "节点显示名称（可选，默认使用类型名称）",
                            },
                            "position_x": {
                                "type": "number",
                                "description": "X 坐标位置（可选，默认自动选择位置）",
                            },
                            "position_y": {
                                "type": "number",
                                "description": "Y 坐标位置（可选，默认自动选择位置）",
                            },
                        },
                        "required": ["node_type"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "delete_node",
                    "description": "请求删除工作流中的指定节点（仅发起确认请求，不会真正删除，需用户确认后调用 confirm_delete_node 完成删除）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "node_id": {
                                "type": "string",
                                "description": "要删除的节点 ID",
                            },
                        },
                        "required": ["node_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "confirm_delete_node",
                    "description": "确认删除节点（仅在用户明确确认后调用，执行真正的删除操作）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "node_id": {
                                "type": "string",
                                "description": "要确认删除的节点 ID",
                            },
                        },
                        "required": ["node_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "connect_nodes",
                    "description": "在两个节点间创建连接（从上游节点输出端口连接到下游节点输入端口）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "from_node_id": {
                                "type": "string",
                                "description": "上游节点 ID（数据来源）",
                            },
                            "to_node_id": {
                                "type": "string",
                                "description": "下游节点 ID（数据去向）",
                            },
                            "from_port_name": {
                                "type": "string",
                                "description": "上游节点的输出端口名称（可选，默认取第一个输出端口）",
                            },
                            "to_port_name": {
                                "type": "string",
                                "description": "下游节点的输入端口名称（可选，默认取第一个输入端口）",
                            },
                        },
                        "required": ["from_node_id", "to_node_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "disconnect_nodes",
                    "description": "断开两个节点之间的连接（从上游节点输出端口到下游节点输入端口的连接线）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "from_node_id": {
                                "type": "string",
                                "description": "上游节点 ID（数据来源）",
                            },
                            "to_node_id": {
                                "type": "string",
                                "description": "下游节点 ID（数据去向）",
                            },
                            "from_port_name": {
                                "type": "string",
                                "description": "上游节点的输出端口名称（可选，默认断开该方向所有连接）",
                            },
                            "to_port_name": {
                                "type": "string",
                                "description": "下游节点的输入端口名称（可选，默认断开该方向所有连接）",
                            },
                        },
                        "required": ["from_node_id", "to_node_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "update_node_config",
                    "description": "更新节点的配置属性（仅允许修改节点 config_schema 中定义的配置项，key 和值类型必须符合 schema 定义，否则会被跳过）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "node_id": {
                                "type": "string",
                                "description": "节点 ID",
                            },
                            "config_updates": {
                                "type": "object",
                                "description": "要更新的配置键值对",
                            },
                        },
                        "required": ["node_id", "config_updates"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_workflow_info",
                    "description": "获取当前工作流的完整信息（节点列表、连接关系等）",
                    "parameters": {
                        "type": "object",
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_node_detail",
                    "description": "查询指定节点的详细信息，包括 id、title、type、position、完整 config、config_schema、输入端口列表（含已连接的上游节点信息）和输出端口列表（含已连接的下游节点信息）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "node_id": {
                                "type": "string",
                                "description": "要查询的节点 ID",
                            },
                        },
                        "required": ["node_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "arrange_nodes",
                    "description": "自动排列节点布局",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "layout_type": {
                                "type": "string",
                                "enum": ["left_to_right", "top_to_bottom", "auto"],
                                "description": "布局方向（默认 auto）",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "run_workflow",
                    "description": "触发当前工作流的执行（运行整个工作流）",
                    "parameters": {
                        "type": "object",
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "save_workflow",
                    "description": "保存当前工作流（将当前画布上的节点和连接持久化到文件）",
                    "parameters": {
                        "type": "object",
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_workflows",
                    "description": "列出所有可用的工作流名称",
                    "parameters": {
                        "type": "object",
                    },
                },
            },
            # ===== 高优先级: 工作流调试工具 =====
            {
                "type": "function",
                "function": {
                    "name": "get_execution_status",
                    "description": "获取当前工作流的执行状态（空闲、运行中、已完成、错误等）",
                    "parameters": {
                        "type": "object",
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_execution_log",
                    "description": "返回最近一次执行的详细日志，包括每个节点的输入数据、输出数据、执行耗时和错误信息",
                    "parameters": {
                        "type": "object",
                    },
                },
            },
            # ===== 高优先级: 工作流脚手架工具 =====
            {
                "type": "function",
                "function": {
                    "name": "generate_workflow_template",
                    "description": "根据自然语言描述，一次性添加一组预设节点并自动连接，形成完整工作流模板",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "description": {
                                "type": "string",
                                "description": "用户需求描述，如'每小时抓取RSS并发送到我的邮箱'",
                            },
                        },
                        "required": ["description"],
                    },
                },
            },
            # ===== 高优先级: 环境管理工具 =====
            {
                "type": "function",
                "function": {
                    "name": "create_workflow_environment",
                    "description": "为当前工作流创建独立的 Python 虚拟环境（基于 uv）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "python_version": {
                                "type": "string",
                                "description": "Python版本，如'3.11'（可选，默认3.11）",
                            },
                        },
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "install_node_dependencies",
                    "description": "安装指定节点所需的所有依赖包到当前工作流虚拟环境",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "node_id": {
                                "type": "string",
                                "description": "目标节点ID，或输入'all'安装所有节点依赖",
                            },
                        },
                        "required": ["node_id"],
                    },
                },
            },
            # ===== 中优先级: 变量管理工具 =====
            {
                "type": "function",
                "function": {
                    "name": "set_workflow_variable",
                    "description": "设置工作流级别的全局变量，可在节点间共享",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "变量名",
                            },
                            "value": {
                                "type": "string",
                                "description": "变量值（JSON字符串格式）",
                            },
                            "overwrite": {
                                "type": "boolean",
                                "description": "是否覆盖已存在的变量（默认true）",
                            },
                        },
                        "required": ["name", "value"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "get_workflow_variable",
                    "description": "读取指定全局变量的值",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "name": {
                                "type": "string",
                                "description": "变量名",
                            },
                        },
                        "required": ["name"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "list_workflow_variables",
                    "description": "以键值对列表形式返回所有全局变量",
                    "parameters": {
                        "type": "object",
                    },
                },
            },
            # ===== 中优先级: 节点市场工具 =====
            {
                "type": "function",
                "function": {
                    "name": "search_community_nodes",
                    "description": "按关键字搜索 GitHub 中的社区节点",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "keyword": {
                                "type": "string",
                                "description": "搜索关键词",
                            },
                            "max_results": {
                                "type": "integer",
                                "description": "最大返回结果数（默认5）",
                            },
                        },
                        "required": ["keyword"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "import_community_node",
                    "description": "从社区导入指定节点到当前工作流可用节点库",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "node_name": {
                                "type": "string",
                                "description": "节点唯一名称，如'rss_reader'",
                            },
                            "version": {
                                "type": "string",
                                "description": "版本号（可选，默认最新）",
                            },
                        },
                        "required": ["node_name"],
                    },
                },
            },
            # ===== 中优先级: 条件逻辑控制工具 =====
            {
                "type": "function",
                "function": {
                    "name": "add_condition_node",
                    "description": "添加一个条件判断节点（If-Else分支），有两个输出端口'true'和'false'",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "title": {
                                "type": "string",
                                "description": "节点标题",
                            },
                            "position_x": {
                                "type": "number",
                                "description": "X坐标位置（可选）",
                            },
                            "position_y": {
                                "type": "number",
                                "description": "Y坐标位置（可选）",
                            },
                        },
                        "required": ["title"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "configure_condition",
                    "description": "配置条件节点的判断表达式",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "node_id": {
                                "type": "string",
                                "description": "条件节点ID",
                            },
                            "expression": {
                                "type": "string",
                                "description": "Python表达式字符串，如'$variable.threshold > 10'",
                            },
                        },
                        "required": ["node_id", "expression"],
                    },
                },
            },
            # ===== 低优先级: 外部集成工具 =====
            {
                "type": "function",
                "function": {
                    "name": "configure_trigger",
                    "description": "配置工作流的自动触发方式（定时、webhook、文件监听等）",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "trigger_type": {
                                "type": "string",
                                "enum": ["schedule", "webhook", "file_watch"],
                                "description": "触发类型：schedule定时/webhook外部回调/file_watch文件变更",
                            },
                            "settings": {
                                "type": "object",
                                "description": "触发配置，如{'cron': '0 * * * *'}或{'path': '/data/incoming'}",
                            },
                        },
                        "required": ["trigger_type", "settings"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "expose_webhook",
                    "description": "将当前工作流暴露为HTTP Webhook接口，方便外部调用",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "URL路径，如'/webhook/my_flow'",
                            },
                            "method": {
                                "type": "string",
                                "enum": ["POST", "GET"],
                                "description": "HTTP方法",
                            },
                        },
                        "required": ["path", "method"],
                    },
                },
            },
            # ===== 低优先级: 高级调试工具 =====
            {
                "type": "function",
                "function": {
                    "name": "debug_node",
                    "description": "单独试运行一个节点，不依赖上游输入，手动提供测试数据",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "node_id": {
                                "type": "string",
                                "description": "目标节点ID",
                            },
                            "input_data": {
                                "type": "object",
                                "description": "测试输入数据（可选，默认空对象）",
                            },
                        },
                        "required": ["node_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "set_breakpoint",
                    "description": "在指定节点设置断点，使工作流执行到该节点时暂停",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "node_id": {
                                "type": "string",
                                "description": "要设置断点的节点ID",
                            },
                        },
                        "required": ["node_id"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "remove_breakpoint",
                    "description": "移除指定节点的断点",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "node_id": {
                                "type": "string",
                                "description": "要移除断点的节点ID",
                            },
                        },
                        "required": ["node_id"],
                    },
                },
            },
            # ===== 低优先级: 画布增强工具 =====
            {
                "type": "function",
                "function": {
                    "name": "duplicate_node_group",
                    "description": "复制一组节点及其内部连接，偏移一定距离粘贴",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "node_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "要复制的节点ID列表",
                            },
                            "offset_x": {
                                "type": "number",
                                "description": "X方向偏移量（默认50）",
                            },
                            "offset_y": {
                                "type": "number",
                                "description": "Y方向偏移量（默认50）",
                            },
                        },
                        "required": ["node_ids"],
                    },
                },
            },
            {
                "type": "function",
                "function": {
                    "name": "enable_node",
                    "description": "启用或禁用节点，被禁用的节点在工作流执行时将被跳过",
                    "parameters": {
                        "type": "object",
                        "properties": {
                            "node_id": {
                                "type": "string",
                                "description": "目标节点ID",
                            },
                            "enabled": {
                                "type": "boolean",
                                "description": "true启用，false禁用",
                            },
                        },
                        "required": ["node_id", "enabled"],
                    },
                },
            },
        ]
