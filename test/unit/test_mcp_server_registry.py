import json

import pytest

from src.core.exceptions import ErrorCode, MozikitError
from src.core.mcp_server_registry import MCPServerDefinition, MCPServerRegistry


def _stdio(server_id="jira", **kwargs):
    return MCPServerDefinition(server_id, "Jira", stdio={"command": "npx", "args": ["-y", "jira"], **kwargs})


def test_registry_persists_outside_main_config(tmp_path):
    registry = MCPServerRegistry(tmp_path / "mcp" / "servers.json")
    registry.add_server(_stdio())
    loaded = MCPServerRegistry(tmp_path / "mcp" / "servers.json")
    assert loaded.get_server("jira").stdio["command"] == "npx"
    assert (tmp_path / "mcp" / "servers.json").exists()


def test_server_id_is_stable_and_update_cannot_rename(tmp_path):
    registry = MCPServerRegistry(tmp_path / "servers.json")
    registry.add_server(_stdio())
    with pytest.raises(MozikitError) as exc:
        registry.update_server("jira", _stdio("work-jira"))
    assert exc.value.code == ErrorCode.MCP_SERVER_INVALID


def test_sensitive_values_must_be_credential_references(tmp_path):
    registry = MCPServerRegistry(tmp_path / "servers.json")
    definition = _stdio(env={"JIRA_TOKEN": "abc123"})
    with pytest.raises(MozikitError) as exc:
        registry.add_server(definition)
    assert exc.value.code == ErrorCode.MCP_CREDENTIAL_REQUIRED


def test_resolve_server_uses_credential_store_without_persisting_secret(tmp_path, monkeypatch):
    registry = MCPServerRegistry(tmp_path / "servers.json")
    monkeypatch.setattr("src.core.mcp_server_registry.store_credential", lambda key, value: "reference")
    monkeypatch.setattr("src.core.mcp_server_registry.retrieve_credential", lambda key, **kwargs: "secret-value")
    registry.add_server(_stdio(env={"JIRA_TOKEN": "{{credential.mcp.jira.token}}"}))
    resolved = registry.resolve_server("jira")
    assert resolved["stdio"]["env"]["JIRA_TOKEN"] == "secret-value"
    assert "secret-value" not in (tmp_path / "servers.json").read_text(encoding="utf-8")


def test_disabled_and_missing_servers_have_structured_errors(tmp_path):
    registry = MCPServerRegistry(tmp_path / "servers.json")
    registry.add_server(_stdio())
    registry.set_enabled("jira", False)
    with pytest.raises(MozikitError) as exc:
        registry.resolve_server("jira")
    assert exc.value.code == ErrorCode.MCP_SERVER_DISABLED
    with pytest.raises(MozikitError) as exc:
        registry.get_server("missing")
    assert exc.value.code == ErrorCode.MCP_SERVER_NOT_FOUND


def test_export_keeps_only_reference_values(tmp_path):
    registry = MCPServerRegistry(tmp_path / "servers.json")
    registry.add_server(_stdio(env={"TOKEN": {"credential": "mcp.jira.token"}}))
    exported = registry.export_servers()
    assert exported["servers"][0]["stdio"]["env"]["TOKEN"] == {"credential": "mcp.jira.token"}
