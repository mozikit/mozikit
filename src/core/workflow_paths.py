"""Safe local paths belonging to one workflow."""

import os
from pathlib import Path, PureWindowsPath
from typing import Union


class WorkflowPathError(ValueError):
    """Raised when a path is invalid or escapes the workflow directory."""


def _normalise_input(value: Union[str, os.PathLike]) -> str:
    if not isinstance(value, (str, os.PathLike)):
        raise WorkflowPathError("workflow path must be a string")
    value = os.fspath(value)
    if not value or not value.strip():
        raise WorkflowPathError("workflow path must not be empty")
    return value.replace("\\", os.sep).replace("/", os.sep)


def _is_absolute_any_platform(value: str) -> bool:
    return Path(value).is_absolute() or PureWindowsPath(value).is_absolute()


class WorkflowPathResolver:
    """Resolve user-facing paths under a workflow root."""

    def __init__(self, workflow_dir: Union[str, os.PathLike]):
        self.workflow_dir = Path(workflow_dir).expanduser().resolve()

    def resolve(self, path, *, for_write=False, must_exist=False, create_parent=False) -> Path:
        raw = _normalise_input(path)
        candidate = Path(raw).expanduser()
        resolved = candidate.resolve() if _is_absolute_any_platform(raw) else (self.workflow_dir / candidate).resolve()
        try:
            resolved.relative_to(self.workflow_dir)
        except ValueError as exc:
            raise WorkflowPathError(f"path escapes workflow directory: {path!r}") from exc
        if must_exist and not resolved.exists():
            raise FileNotFoundError(f"workflow file does not exist: {path}")
        if for_write and create_parent:
            resolved.parent.mkdir(parents=True, exist_ok=True)
        return resolved

    def relative(self, path) -> str:
        return self.resolve(path).relative_to(self.workflow_dir).as_posix()


def resolve_workflow_path(workflow_dir, path, **kwargs) -> Path:
    return WorkflowPathResolver(workflow_dir).resolve(path, **kwargs)
