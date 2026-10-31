"""Verify the official SDK against an independent agent process over real stdio."""

import asyncio
import json
import sys
from pathlib import Path

import pytest

pytest.importorskip("acp")

from src.core.acp_client import ACPClient
from src.core.exceptions import ErrorCode, MozikitError


AGENT = Path(__file__).resolve().parents[1] / "fixtures" / "fake_acp_agent.py"


def client(tmp_path, mode="normal", **kwargs):
    return ACPClient(
        sys.executable,
        [str(AGENT), mode, str(tmp_path / "wire.jsonl")],
        cwd=tmp_path,
        connect_timeout=2,
        cancel_timeout=0.2,
        **kwargs,
    )


def wire(tmp_path):
    return [
        json.loads(line) for line in (tmp_path / "wire.jsonl").read_text().splitlines()
    ]


@pytest.mark.asyncio
async def test_handshake_stream_order_and_multiple_turns(tmp_path):
    seen = []
    async with client(tmp_path, on_update=seen.append) as agent:
        assert agent.initialization["agentInfo"]["name"] == "fake-acp"
        await agent.new_session()
        first = await agent.prompt("first turn")
        second = await agent.prompt("second turn")
        process = agent._process
        assert first.text == second.text == "你好，ACP"
        assert first.stop_reason == "end_turn"
        assert [event["update"]["sessionUpdate"] for event in first.updates] == [
            "agent_thought_chunk",
            "tool_call",
            "agent_message_chunk",
            "agent_message_chunk",
            "tool_call_update",
        ]
        assert len(seen) == 10
        assert all(event["sessionId"] == "test-session" for event in seen)
    assert process.returncode is not None
    requests = wire(tmp_path)
    assert requests[0]["params"]["protocolVersion"] == 1
    # ACP permits omitted capability fields; omission means unsupported.
    caps = requests[0]["params"].get("clientCapabilities") or {}
    assert not caps.get("terminal", False)
    assert not (caps.get("fs") or {}).get("readTextFile", False)
    assert not (caps.get("fs") or {}).get("writeTextFile", False)
    new_session = next(r for r in requests if r.get("method") == "session/new")
    assert new_session["params"]["cwd"] == str(tmp_path)
    assert new_session["params"]["mcpServers"] == []


@pytest.mark.asyncio
async def test_authentication_and_loading_advertised_session(tmp_path):
    seen = []
    async with client(tmp_path, "auth", on_update=seen.append) as agent:
        with pytest.raises(MozikitError) as error:
            await agent.new_session()
        assert error.value.code == ErrorCode.ACP_AUTH_REQUIRED
        await agent.authenticate("test-login")
        await agent.load_session("saved-session")
        result = await agent.prompt("hello")
        assert result.session_id == "saved-session"
        assert result.text == "你好，ACP"
        assert seen[0]["update"]["content"]["text"] == "previous turn"
        assert len(result.updates) == 5


@pytest.mark.asyncio
async def test_unadvertised_authentication_and_load_are_not_sent(tmp_path):
    async with client(tmp_path, "no-load") as agent:
        with pytest.raises(MozikitError) as error:
            await agent.authenticate("unknown")
        assert error.value.code == ErrorCode.ACP_AUTHENTICATION_FAILED
        with pytest.raises(MozikitError) as error:
            await agent.load_session("saved")
        assert error.value.code == ErrorCode.ACP_CAPABILITY_UNSUPPORTED
    assert [r["method"] for r in wire(tmp_path)] == ["initialize"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "decision,expected",
    [
        (None, {"outcome": "selected", "optionId": "no"}),
        ("yes", {"outcome": "selected", "optionId": "yes"}),
        ("invented", {"outcome": "cancelled"}),
    ],
)
async def test_permission_defaults_and_explicit_host_decision(
    tmp_path, decision, expected
):
    async def decide(event):
        assert event["toolCall"]["toolCallId"] == "edit-1"
        return decision

    kwargs = {"permission_handler": decide} if decision is not None else {}
    async with client(tmp_path, "permission", **kwargs) as agent:
        await agent.new_session()
        result = await agent.prompt("edit")
        assert json.loads(result.text) == expected


@pytest.mark.asyncio
async def test_timeout_sends_cancel_before_disconnecting(tmp_path):
    async with client(tmp_path, "wait") as agent:
        await agent.new_session()
        with pytest.raises(MozikitError) as error:
            await agent.prompt("wait", timeout=0.05)
        assert error.value.code == ErrorCode.ACP_TIMEOUT
        assert agent._connection is not None
    assert any(r.get("method") == "session/cancel" for r in wire(tmp_path))


@pytest.mark.asyncio
async def test_cancel_and_parallel_prompt_guard(tmp_path):
    async with client(tmp_path, "wait") as agent:
        await agent.new_session()
        turn = asyncio.create_task(agent.prompt("wait"))
        while agent._prompt_task is None:
            await asyncio.sleep(0)
        with pytest.raises(MozikitError) as error:
            await agent.prompt("parallel")
        assert error.value.code == ErrorCode.ACP_PROMPT_RUNNING
        await agent.cancel()
        assert (await turn).stop_reason == "cancelled"


@pytest.mark.asyncio
async def test_caller_cancellation_notifies_agent(tmp_path):
    async with client(tmp_path, "wait") as agent:
        await agent.new_session()
        turn = asyncio.create_task(agent.prompt("wait"))
        while agent._prompt_task is None:
            await asyncio.sleep(0)
        turn.cancel()
        with pytest.raises(asyncio.CancelledError):
            await turn
    assert any(r.get("method") == "session/cancel" for r in wire(tmp_path))


@pytest.mark.asyncio
async def test_agent_ignoring_cancel_is_closed(tmp_path):
    async with client(tmp_path, "ignore-cancel") as agent:
        process = agent._process
        await agent.new_session()
        with pytest.raises(MozikitError) as error:
            await agent.prompt("wait", timeout=0.05)
        assert error.value.code == ErrorCode.ACP_TIMEOUT
        assert agent._connection is None
        assert process.returncode is not None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "mode,code",
    [
        ("incompatible", ErrorCode.ACP_PROTOCOL_ERROR),
        ("malformed", ErrorCode.ACP_PROTOCOL_ERROR),
        ("exit", ErrorCode.ACP_PROCESS_EXITED),
    ],
)
async def test_handshake_failures_cleanup(tmp_path, mode, code):
    agent = client(tmp_path, mode)
    with pytest.raises(MozikitError) as error:
        await agent.connect()
    assert error.value.code == code
    assert agent._transport is None


@pytest.mark.asyncio
async def test_missing_executable_is_structured_error(tmp_path):
    agent = ACPClient(str(tmp_path / "does-not-exist"), cwd=tmp_path)
    with pytest.raises(MozikitError) as error:
        await agent.connect()
    assert error.value.code == ErrorCode.ACP_PROCESS_START_FAILED
    assert agent._transport is None


@pytest.mark.asyncio
async def test_initialization_timeout_cleans_up_process(tmp_path):
    agent = ACPClient(
        sys.executable,
        [str(AGENT), "hang-init", str(tmp_path / "wire.jsonl")],
        cwd=tmp_path,
        connect_timeout=0.1,
    )
    with pytest.raises(MozikitError) as error:
        await agent.connect()
    assert error.value.code == ErrorCode.ACP_TIMEOUT
    assert agent._transport is None


@pytest.mark.asyncio
async def test_failed_authentication_does_not_echo_agent_diagnostics(tmp_path):
    async with client(tmp_path, "auth-fail") as agent:
        with pytest.raises(MozikitError) as error:
            await agent.authenticate("test-login")
        assert error.value.code == ErrorCode.ACP_AUTHENTICATION_FAILED
        assert "secret diagnostic" not in str(error.value)


@pytest.mark.asyncio
async def test_session_and_prompt_state_validation(tmp_path):
    agent = client(tmp_path)
    with pytest.raises(MozikitError) as error:
        await agent.new_session()
    assert error.value.code == ErrorCode.ACP_INVALID_STATE
    async with agent:
        with pytest.raises(MozikitError) as error:
            await agent.prompt("no session yet")
        assert error.value.code == ErrorCode.ACP_INVALID_STATE
        await agent.new_session()
        with pytest.raises(MozikitError) as error:
            await agent.prompt(" ")
        assert error.value.code == ErrorCode.INVALID_PARAMETER
