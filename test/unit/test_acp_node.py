from dataclasses import replace
from threading import Event
from types import SimpleNamespace

import pytest

from src.core.acp_node_executor import ACPAgentNativeExecutor
from src.core.exceptions import ErrorCode, MozikitError
from src.core.node_extension_registries import (
    NativeExecutionContext,
    execute_native,
    native_executors,
)
from src.core.node_registry import NodeRegistry


@pytest.mark.parametrize(
    "override",
    [
        {"agent": ""},
        {"prompt": " "},
        {"prompt": {"bad": True}},
        {"args": "--acp"},
        {"args": [1]},
        {"cwd": "/path/that/does/not/exist"},
        {"timeout": 0},
        {"timeout": float("nan")},
        {"timeout": True},
        {"auth_method": 3},
    ],
)
def test_invalid_node_config_does_not_start_agent(override, monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("Invalid config must be rejected before spawning an agent")

    monkeypatch.setattr("src.core.acp_node_executor.ACPClient", unexpected)
    node = SimpleNamespace(
        config={"agent": "not-started", "prompt": "hello", **override}
    )
    with pytest.raises(MozikitError) as error:
        ACPAgentNativeExecutor().execute(node=node, input_data={}, context={})
    assert error.value.code == ErrorCode.NODE_VALIDATION_FAILED


def test_acp_core_registration_restores_contract_after_stale_snapshot(
    tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    registry = NodeRegistry()
    definition = registry.get_node("acp_agent")
    assert definition.name == "ACP Agent"
    registry._nodes["acp_agent"] = replace(
        definition,
        config_schema={},
        input_schema={},
        output_schema={},
        dependencies=["stale-dependency"],
        registrations={"native_executor": {"id": "debug"}},
    )
    registry._register_core_nodes()
    restored = registry.get_node("acp_agent")
    assert restored.registrations["native_executor"]["id"] == "acp_agent"
    assert restored.input_schema["prompt"]["type"] == "string"
    assert restored.output_schema["text"]["type"] == "string"
    assert restored.config_schema["args"]["type"] == "string_list"
    assert not restored.dependencies


def test_host_context_is_opt_in_for_native_extensions(monkeypatch, tmp_path):
    class LegacyExecutor:
        def execute(self, *, value):
            return {"value": value}

    class NewExecutor:
        supports_execution_context = True

        def execute(self, *, value, execution_context):
            assert execution_context.workflow_dir == tmp_path
            assert execution_context.stop_event.is_set()
            return {"value": value}

    monkeypatch.setitem(native_executors._items, "test-legacy", LegacyExecutor())
    monkeypatch.setitem(native_executors._items, "test-new", NewExecutor())
    stop = Event()
    stop.set()
    runtime = NativeExecutionContext(tmp_path, stop)
    assert execute_native("test-legacy", value=1, execution_context=runtime) == {
        "value": 1
    }
    assert execute_native("test-new", value=2, execution_context=runtime) == {
        "value": 2
    }
