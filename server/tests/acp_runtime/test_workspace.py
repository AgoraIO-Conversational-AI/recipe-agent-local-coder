"""Workspace Scope persistence tests through the public service API."""

import json
import stat

import pytest

from acp_runtime.workspace import WorkspaceConfigStore, WorkspaceService


def test_unconfigured_store_reports_codex_profile(tmp_path):
    service = WorkspaceService(WorkspaceConfigStore(tmp_path / "workspace.json"))

    status = service.status()

    assert status.state == "unconfigured"
    assert status.profile.id == "codex"
    assert status.profile.label == "Codex"
    assert status.profile.requires_primary_directory is True
    assert status.profile.supports_additional_directories is False
    assert status.workspace is None


def test_select_resolves_and_persists_one_primary_directory(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    store = WorkspaceConfigStore(tmp_path / "state" / "workspace.json")

    selected = WorkspaceService(store).select(str(project / ".." / "project"))
    restored = WorkspaceService(store).status()

    assert selected.state == "ready"
    assert selected.workspace is not None
    assert selected.workspace.primary_directory == str(project.resolve())
    assert selected.workspace.label == "project"
    assert restored == selected
    assert json.loads(store.path.read_text(encoding="utf-8")) == {
        "schema_version": "1.0",
        "id": selected.workspace.id,
        "label": "project",
        "primary_directory": str(project.resolve()),
    }
    assert stat.S_IMODE(store.path.stat().st_mode) == 0o600


def test_missing_saved_directory_reports_invalid_without_deleting_record(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    store = WorkspaceConfigStore(tmp_path / "workspace.json")
    WorkspaceService(store).select(str(project))
    project.rmdir()

    status = WorkspaceService(store).status()

    assert status.state == "invalid"
    assert status.workspace is not None
    assert status.workspace.primary_directory == str(project.resolve())
    assert store.path.exists()


def test_select_rejects_missing_path_and_regular_file(tmp_path):
    service = WorkspaceService(WorkspaceConfigStore(tmp_path / "workspace.json"))
    regular_file = tmp_path / "file.txt"
    regular_file.write_text("not a folder", encoding="utf-8")

    with pytest.raises(ValueError, match="existing directory"):
        service.select(str(tmp_path / "missing"))
    with pytest.raises(ValueError, match="existing directory"):
        service.select(str(regular_file))

    assert service.status().state == "unconfigured"


def test_clear_removes_only_saved_workspace_selection(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    store = WorkspaceConfigStore(tmp_path / "state" / "workspace.json")
    service = WorkspaceService(store)
    service.select(str(project))

    status = service.clear()

    assert status.state == "unconfigured"
    assert status.workspace is None
    assert not store.path.exists()
    assert project.is_dir()
