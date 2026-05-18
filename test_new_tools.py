#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试新添加的 AI Agent 工具
"""

import json
import sys

sys.path.insert(0, ".")

from src.core.ai_tool_executor import ErrorCode


def test_error_codes():
    """测试新错误码"""
    print("测试新错误码...")

    # 高优先级
    assert ErrorCode.WORKFLOW_NOT_RUNNING == "WORKFLOW_NOT_RUNNING"
    assert ErrorCode.NO_EXECUTION_LOG == "NO_EXECUTION_LOG"
    assert ErrorCode.TEMPLATE_GENERATION_FAILED == "TEMPLATE_GENERATION_FAILED"
    assert ErrorCode.INVALID_DESCRIPTION == "INVALID_DESCRIPTION"
    assert ErrorCode.ENVIRONMENT_ALREADY_EXISTS == "ENVIRONMENT_ALREADY_EXISTS"
    assert ErrorCode.ENVIRONMENT_CREATION_FAILED == "ENVIRONMENT_CREATION_FAILED"
    assert ErrorCode.NO_DEPENDENCIES == "NO_DEPENDENCIES"
    assert ErrorCode.INSTALLATION_FAILED == "INSTALLATION_FAILED"

    # 中优先级
    assert ErrorCode.VARIABLE_ALREADY_EXISTS == "VARIABLE_ALREADY_EXISTS"
    assert ErrorCode.VARIABLE_NOT_FOUND == "VARIABLE_NOT_FOUND"
    assert ErrorCode.INVALID_VALUE_TYPE == "INVALID_VALUE_TYPE"
    assert ErrorCode.SEARCH_FAILED == "SEARCH_FAILED"
    assert ErrorCode.NETWORK_ERROR == "NETWORK_ERROR"
    assert ErrorCode.NODE_NOT_FOUND_IN_COMMUNITY == "NODE_NOT_FOUND_IN_COMMUNITY"
    assert ErrorCode.IMPORT_FAILED == "IMPORT_FAILED"
    assert ErrorCode.NODE_ALREADY_EXISTS == "NODE_ALREADY_EXISTS"
    assert ErrorCode.NODE_TYPE_NOT_AVAILABLE == "NODE_TYPE_NOT_AVAILABLE"
    assert ErrorCode.INVALID_EXPRESSION == "INVALID_EXPRESSION"
    assert ErrorCode.NOT_A_CONDITION_NODE == "NOT_A_CONDITION_NODE"

    # 低优先级
    assert ErrorCode.UNSUPPORTED_TRIGGER_TYPE == "UNSUPPORTED_TRIGGER_TYPE"
    assert ErrorCode.INVALID_TRIGGER_CONFIG == "INVALID_TRIGGER_CONFIG"
    assert ErrorCode.WEBHOOK_ALREADY_EXISTS == "WEBHOOK_ALREADY_EXISTS"
    assert ErrorCode.PORT_IN_USE == "PORT_IN_USE"
    assert ErrorCode.EXECUTION_FAILED == "EXECUTION_FAILED"
    assert ErrorCode.BREAKPOINT_ALREADY_SET == "BREAKPOINT_ALREADY_SET"
    assert ErrorCode.BREAKPOINT_NOT_FOUND == "BREAKPOINT_NOT_FOUND"
    assert ErrorCode.DUPLICATION_FAILED == "DUPLICATION_FAILED"

    print("✓ 所有新错误码定义正确")


def test_tool_definitions_count():
    """测试工具定义数量"""
    from src.core.ai_chat_service import AIChatService

    print("\n测试工具定义...")

    tool_definitions = AIChatService._build_tool_definitions()

    # 原有12个 + 新增19个 = 31个工具
    expected_count = 31
    actual_count = len(tool_definitions)

    print(f"工具总数: {actual_count} (预期: {expected_count})")

    tool_names = [tool["function"]["name"] for tool in tool_definitions]
    print(f"\n工具列表: {tool_names}")

    # 验证新工具存在
    new_tools = [
        # 高优先级
        "get_execution_status",
        "get_execution_log",
        "generate_workflow_template",
        "create_workflow_environment",
        "install_node_dependencies",
        # 中优先级
        "set_workflow_variable",
        "get_workflow_variable",
        "list_workflow_variables",
        "search_community_nodes",
        "import_community_node",
        "add_condition_node",
        "configure_condition",
        # 低优先级
        "configure_trigger",
        "expose_webhook",
        "debug_node",
        "set_breakpoint",
        "remove_breakpoint",
        "duplicate_node_group",
        "enable_node",
    ]

    missing = [tool for tool in new_tools if tool not in tool_names]
    if missing:
        print(f"✗ 缺少工具: {missing}")
        return False

    print("✓ 所有新工具已定义")
    return True


def test_workflow_tab_methods():
    """测试 WorkflowTabWidget 新增方法"""
    from src.views.workflow_tab_widget import WorkflowTabWidget

    print("\n测试 WorkflowTabWidget 新增方法...")

    # 检查方法是否存在
    methods = [
        "get_execution_status",
        "get_execution_log",
        "_clear_execution_log",
        "_append_execution_log",
        "set_variable",
        "get_variable",
        "list_variables",
        "set_breakpoint",
        "remove_breakpoint",
        "has_breakpoint",
        "list_breakpoints",
    ]

    for method in methods:
        assert hasattr(WorkflowTabWidget, method), f"缺少方法: {method}"

    print("✓ WorkflowTabWidget 新增方法已添加")


def test_executor_handlers():
    """测试 AIToolExecutor 新增方法"""
    from src.core.ai_tool_executor import AIToolExecutor

    print("\n测试 AIToolExecutor 新增方法...")

    methods = [
        # 高优先级
        "get_execution_status",
        "get_execution_log",
        "generate_workflow_template",
        "create_workflow_environment",
        "install_node_dependencies",
        # 中优先级
        "set_workflow_variable",
        "get_workflow_variable",
        "list_workflow_variables",
        "search_community_nodes",
        "import_community_node",
        "add_condition_node",
        "configure_condition",
        # 低优先级
        "configure_trigger",
        "expose_webhook",
        "debug_node",
        "set_breakpoint",
        "remove_breakpoint",
        "duplicate_node_group",
        "enable_node",
    ]

    for method in methods:
        assert hasattr(AIToolExecutor, method), f"缺少方法: {method}"

    print("✓ AIToolExecutor 新增方法已添加")


def test_tool_call_argument_normalization():
    """测试工具调用参数会被规范化为合法 JSON 字符串"""
    from src.core.ai_chat_service import AIChatService

    print("\n测试 tool_call 参数规范化...")

    raw_tool_calls = [
        {
            "id": "call_invalid",
            "type": "function",
            "function": {"name": "get_workflow_info", "arguments": "{bad json"},
        },
        {
            "id": "call_dict",
            "type": "function",
            "function": {
                "name": "add_node",
                "arguments": {"node_type": "sqlite_connection"},
            },
        },
        {
            "id": "call_empty",
            "type": "function",
            "function": {"name": "list_workflows", "arguments": ""},
        },
    ]

    normalized = AIChatService._normalize_tool_calls(raw_tool_calls)
    assert len(normalized) == 3
    assert normalized[0]["function"]["arguments"] == "{}"
    assert json.loads(normalized[1]["function"]["arguments"]) == {
        "node_type": "sqlite_connection"
    }
    assert normalized[2]["function"]["arguments"] == "{}"

    for tool_call in normalized:
        assert isinstance(tool_call["function"]["arguments"], str)
        assert isinstance(json.loads(tool_call["function"]["arguments"]), dict)

    print("✓ tool_call 参数规范化正确")


def test_stream_tool_call_merge_by_index():
    """测试流式 tool_call 增量按 index 合并"""
    from src.core.ai_chat_service import AIChatService

    print("\n测试流式 tool_call 增量合并...")

    tool_calls_map = {}
    AIChatService._merge_stream_tool_call(
        tool_calls_map,
        {"index": 0, "function": {"name": "add_node"}},
    )
    AIChatService._merge_stream_tool_call(
        tool_calls_map,
        {
            "index": 0,
            "id": "call_123",
            "function": {"arguments": '{"node_type":"sqlite_connect"'},
        },
    )
    AIChatService._merge_stream_tool_call(
        tool_calls_map,
        {"index": 0, "function": {"arguments": ',"title":"SQLite"}'}},
    )

    merged = tool_calls_map["0"]
    assert merged["id"] == "call_123"
    assert merged["function"]["name"] == "add_node"
    assert json.loads(merged["function"]["arguments"]) == {
        "node_type": "sqlite_connect",
        "title": "SQLite",
    }

    print("✓ 流式 tool_call 增量合并正确")


def test_orphan_tool_messages_are_removed_for_api():
    """测试发送 API 前会移除孤儿 tool 消息"""
    from src.core.ai_chat_service import AIChatService

    print("\n测试孤儿 tool 消息清理...")

    messages = [
        {"role": "user", "content": "hi"},
        {"role": "tool", "tool_call_id": "missing", "content": "orphan"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "call_1",
                    "type": "function",
                    "function": {"name": "list_workflows", "arguments": "{}"},
                }
            ],
        },
        {"role": "tool", "tool_call_id": "call_1", "content": ""},
    ]

    normalized = AIChatService._normalize_messages_for_api(messages)
    assert len(normalized) == 3
    assert normalized[0]["role"] == "user"
    assert normalized[1]["role"] == "assistant"
    assert normalized[2]["role"] == "tool"
    assert normalized[2]["content"] == "执行完成"

    print("✓ 孤儿 tool 消息清理正确")


def test_tool_call_signature_normalizes_arguments():
    """测试工具调用签名会规范化参数顺序"""
    from src.core.ai_chat_service import AIChatService

    print("\n测试 tool_call 签名规范化...")

    first = {
        "function": {
            "name": "add_node",
            "arguments": '{"title":"SQLite","node_type":"sqlite_connect"}',
        }
    }
    second = {
        "function": {
            "name": "add_node",
            "arguments": '{"node_type":"sqlite_connect","title":"SQLite"}',
        }
    }

    assert AIChatService._tool_call_signature(
        first
    ) == AIChatService._tool_call_signature(second)

    print("✓ tool_call 签名规范化正确")


if __name__ == "__main__":
    print("=" * 60)
    print("LocalFlow AI Agent 工具扩展测试")
    print("=" * 60)

    try:
        test_error_codes()
        test_tool_definitions_count()
        test_workflow_tab_methods()
        test_executor_handlers()
        test_tool_call_argument_normalization()
        test_stream_tool_call_merge_by_index()
        test_orphan_tool_messages_are_removed_for_api()
        test_tool_call_signature_normalizes_arguments()

        print("\n" + "=" * 60)
        print("✓ 所有测试通过!")
        print("=" * 60)

    except Exception as e:
        print(f"\n✗ 测试失败: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
