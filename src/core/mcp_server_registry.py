"""Application-wide MCP Server definitions.

This module deliberately contains no MCP process, socket, or protocol
lifecycle.  ``MCPClientManager`` (a later layer) consumes ``resolve_server``.
"""
from __future__ import annotations

import copy
import json
import re
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from ._file_utils import atomic_write_json_sync
from .credential_store import retrieve_credential, store_credential
from .exceptions import ErrorCode, MozikitError
from .runtime_paths import get_mcp_servers_path

_CREDENTIAL_RE = re.compile(r"\{\{\s*credential\.([^{}\s]+)\s*\}\}")
_TRANSPORTS = {"stdio", "streamable_http"}
_SENSITIVE_NAME_RE = re.compile(r"(?:token|password|passwd|secret|api[_-]?key|authorization|cookie)", re.I)


@dataclass
class ValidationResult:
    ok: bool
    code: str = "OK"
    message: str = ""
    missing_credentials: List[str] = field(default_factory=list)


@dataclass
class MCPServerDefinition:
    id: str
    name: str
    description: str = ""
    enabled: bool = True
    transport: str = "stdio"
    stdio: Optional[Dict[str, Any]] = None
    http: Optional[Dict[str, Any]] = None
    metadata: Dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "description": self.description,
            "enabled": self.enabled, "transport": self.transport,
            "stdio": copy.deepcopy(self.stdio), "http": copy.deepcopy(self.http),
            "metadata": copy.deepcopy(self.metadata),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MCPServerDefinition":
        return cls(
            id=str(data.get("id", "")), name=str(data.get("name", "")),
            description=str(data.get("description", "")),
            enabled=bool(data.get("enabled", True)),
            transport=str(data.get("transport", "stdio")),
            stdio=copy.deepcopy(data.get("stdio")), http=copy.deepcopy(data.get("http")),
            metadata=copy.deepcopy(data.get("metadata") or {}),
        )


class MCPServerRegistry:
    """The sole persistent owner of user-configured MCP Servers."""

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path else get_mcp_servers_path()
        self._lock = threading.RLock()
        self._servers: Dict[str, MCPServerDefinition] = {}
        self._load()

    def list_servers(self) -> List[MCPServerDefinition]:
        with self._lock:
            return [copy.deepcopy(server) for server in self._servers.values()]

    def get_server(self, server_id: str) -> MCPServerDefinition:
        with self._lock:
            server = self._servers.get(server_id)
            if server is None:
                raise MozikitError(ErrorCode.MCP_SERVER_NOT_FOUND, f"MCP Server not found: {server_id}")
            return copy.deepcopy(server)

    def add_server(self, definition: MCPServerDefinition) -> MCPServerDefinition:
        self._validate_definition(definition)
        with self._lock:
            if definition.id in self._servers:
                raise MozikitError(ErrorCode.MCP_SERVER_ALREADY_EXISTS, f"MCP Server already exists: {definition.id}")
            definition = copy.deepcopy(definition)
            now = _now()
            definition.metadata.setdefault("created_at", now)
            definition.metadata["updated_at"] = now
            self._servers[definition.id] = definition
            self._save()
            return copy.deepcopy(definition)

    def update_server(self, server_id: str, definition: MCPServerDefinition) -> MCPServerDefinition:
        if definition.id != server_id:
            raise MozikitError(ErrorCode.MCP_SERVER_INVALID, "Server ID cannot be changed after creation")
        self._validate_definition(definition)
        with self._lock:
            if server_id not in self._servers:
                raise MozikitError(ErrorCode.MCP_SERVER_NOT_FOUND, f"MCP Server not found: {server_id}")
            updated = copy.deepcopy(definition)
            updated.metadata["created_at"] = self._servers[server_id].metadata.get("created_at", _now())
            updated.metadata["updated_at"] = _now()
            self._servers[server_id] = updated
            self._save()
            return copy.deepcopy(updated)

    def remove_server(self, server_id: str, references: Optional[Iterable[str]] = None,
                      delete_anyway: bool = False) -> None:
        with self._lock:
            if server_id not in self._servers:
                raise MozikitError(ErrorCode.MCP_SERVER_NOT_FOUND, f"MCP Server not found: {server_id}")
            refs = list(references or [])
            if refs and not delete_anyway:
                raise MozikitError(ErrorCode.MCP_SERVER_IN_USE,
                                   f"MCP Server {server_id} is used by {len(refs)} workflow(s)")
            del self._servers[server_id]
            self._save()

    def set_enabled(self, server_id: str, enabled: bool) -> MCPServerDefinition:
        server = self.get_server(server_id)
        server.enabled = bool(enabled)
        return self.update_server(server_id, server)

    def validate_server(self, server_id: str) -> ValidationResult:
        try:
            server = self.get_server(server_id)
            self._validate_definition(server)
            missing = sorted(set(_credential_refs(server.to_dict())) - set(_available_credentials(server)))
            if missing:
                return ValidationResult(False, ErrorCode.MCP_CREDENTIAL_REQUIRED.value,
                                        "Required MCP credentials are missing", missing)
            return ValidationResult(True)
        except MozikitError as exc:
            return ValidationResult(False, exc.code.value, exc.message)

    def resolve_server(self, server_id: str) -> Dict[str, Any]:
        server = self.get_server(server_id)
        if not server.enabled:
            raise MozikitError(ErrorCode.MCP_SERVER_DISABLED, f"MCP Server is disabled: {server_id}")
        result = server.to_dict()
        return _resolve_values(result, server_id)

    def store_credential(self, server_id: str, name: str, value: str) -> str:
        self.get_server(server_id)
        if not name or not value:
            raise MozikitError(ErrorCode.MCP_SERVER_INVALID, "Credential name and value are required")
        return store_credential(f"mcp.{server_id}.{name}", value)

    def export_servers(self) -> Dict[str, Any]:
        # Definitions are already reference-only; deep copy prevents callers
        # from mutating the registry through the export result.
        return {"version": 1, "servers": [s.to_dict() for s in self.list_servers()]}

    def export_to(self, path: Path) -> None:
        atomic_write_json_sync(Path(path), self.export_servers())

    def _load(self) -> None:
        if not self.path.is_file():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            entries = raw.get("servers", []) if isinstance(raw, dict) else raw
            for entry in entries:
                definition = MCPServerDefinition.from_dict(entry)
                self._validate_definition(definition)
                if definition.id in self._servers:
                    raise ValueError(f"duplicate server id: {definition.id}")
                self._servers[definition.id] = definition
        except (OSError, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise MozikitError(ErrorCode.CONFIG_LOAD_FAILED, f"Unable to load MCP Server Registry: {self.path}", cause=exc)

    def _save(self) -> None:
        atomic_write_json_sync(self.path, {"version": 1, "servers": [s.to_dict() for s in self._servers.values()]})

    @staticmethod
    def _validate_definition(server: MCPServerDefinition) -> None:
        if not server.id or not re.fullmatch(r"[a-z0-9][a-z0-9._-]*", server.id):
            raise MozikitError(ErrorCode.MCP_SERVER_INVALID, "Server ID must use lowercase letters, numbers, '.', '_' or '-'")
        if not server.name.strip() or server.transport not in _TRANSPORTS:
            raise MozikitError(ErrorCode.MCP_SERVER_INVALID, "Server name or transport is invalid")
        if server.transport == "stdio":
            if not isinstance(server.stdio, dict) or not isinstance(server.stdio.get("command"), str) or not server.stdio["command"].strip():
                raise MozikitError(ErrorCode.MCP_SERVER_INVALID, "STDIO requires a command")
            if server.http is not None:
                raise MozikitError(ErrorCode.MCP_SERVER_INVALID, "STDIO Server cannot define HTTP configuration")
        else:
            if not isinstance(server.http, dict) or not isinstance(server.http.get("url"), str) or not server.http["url"].strip():
                raise MozikitError(ErrorCode.MCP_SERVER_INVALID, "Streamable HTTP requires a URL")
            if server.stdio is not None:
                raise MozikitError(ErrorCode.MCP_SERVER_INVALID, "HTTP Server cannot define STDIO configuration")
        for key, value in _sensitive_values(server.to_dict()):
            if isinstance(value, str) and value and not _CREDENTIAL_RE.search(value):
                raise MozikitError(ErrorCode.MCP_CREDENTIAL_REQUIRED, f"Sensitive field must use a credential reference: {key}")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sensitive_values(value: Any, prefix: str = ""):
    if isinstance(value, dict):
        for key, item in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            if _SENSITIVE_NAME_RE.search(str(key)):
                yield path, item
            yield from _sensitive_values(item, path)
    elif isinstance(value, list):
        for i, item in enumerate(value):
            yield from _sensitive_values(item, f"{prefix}[{i}]")


def _credential_refs(value: Any) -> List[str]:
    refs: List[str] = []
    if isinstance(value, dict):
        for item in value.values():
            if isinstance(item, dict) and isinstance(item.get("credential"), str):
                refs.append(item["credential"])
            refs.extend(_credential_refs(item))
    elif isinstance(value, list):
        for item in value:
            refs.extend(_credential_refs(item))
    elif isinstance(value, str):
        refs.extend(m.group(1) for m in _CREDENTIAL_RE.finditer(value))
    return refs


def _available_credentials(server: MCPServerDefinition) -> List[str]:
    available = []
    for ref in _credential_refs(server.to_dict()):
        if retrieve_credential(ref, skip_legacy=True):
            available.append(ref)
    return available


def _resolve_values(value: Any, server_id: str) -> Any:
    if isinstance(value, dict):
        if set(value) == {"credential"}:
            ref = value["credential"]
            resolved = retrieve_credential(ref, skip_legacy=True)
            if not resolved:
                raise MozikitError(ErrorCode.MCP_CREDENTIAL_REQUIRED, f"Credential required: {ref}")
            return resolved
        return {key: _resolve_values(item, server_id) for key, item in value.items()}
    if isinstance(value, list):
        return [_resolve_values(item, server_id) for item in value]
    if isinstance(value, str):
        def replace(match):
            resolved = retrieve_credential(match.group(1), skip_legacy=True)
            if not resolved:
                raise MozikitError(ErrorCode.MCP_CREDENTIAL_REQUIRED, f"Credential required: {match.group(1)}")
            return resolved
        return _CREDENTIAL_RE.sub(replace, value)
    return value


_default_registry: Optional[MCPServerRegistry] = None
_default_lock = threading.Lock()


def get_registry() -> MCPServerRegistry:
    """Return the process-wide application MCP Server Registry."""
    global _default_registry
    with _default_lock:
        if _default_registry is None:
            _default_registry = MCPServerRegistry()
        return _default_registry
