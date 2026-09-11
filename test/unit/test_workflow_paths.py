from pathlib import Path

import pytest

from src.core.workflow_paths import WorkflowPathError, WorkflowPathResolver


def test_resolves_portable_relative_path_and_creates_parent(tmp_path):
    resolver = WorkflowPathResolver(tmp_path / "workflow")
    result = resolver.resolve("artifacts\\message.html", for_write=True, create_parent=True)
    assert result == (tmp_path / "workflow" / "artifacts" / "message.html").resolve()
    assert result.parent.is_dir()


def test_rejects_parent_escape_for_write_and_read(tmp_path):
    resolver = WorkflowPathResolver(tmp_path / "workflow")
    with pytest.raises(WorkflowPathError):
        resolver.resolve("../../outside.txt", for_write=True)
    with pytest.raises(WorkflowPathError):
        resolver.resolve("../outside.txt")


def test_existing_file_and_missing_file(tmp_path):
    resolver = WorkflowPathResolver(tmp_path / "workflow")
    file_path = resolver.resolve("assets/input.txt", for_write=True, create_parent=True)
    file_path.write_text("hello", encoding="utf-8")
    assert resolver.resolve("assets/input.txt", must_exist=True) == file_path
    with pytest.raises(FileNotFoundError):
        resolver.resolve("assets/missing.txt", must_exist=True)


def test_absolute_path_inside_workflow_is_allowed(tmp_path):
    resolver = WorkflowPathResolver(tmp_path / "workflow")
    result = resolver.resolve(str((tmp_path / "workflow" / "assets" / "x.txt").resolve()))
    assert result == (tmp_path / "workflow" / "assets" / "x.txt").resolve()
