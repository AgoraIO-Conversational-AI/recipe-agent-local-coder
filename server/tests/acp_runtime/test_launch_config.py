"""Advanced launcher configuration through the local runtime boundary."""

import pytest

from acp_runtime.launch import apply_workspace_override
from acp_runtime.workspace import WorkspaceConfigStore, WorkspaceService


def test_workspace_override_uses_normal_selection_and_persistence(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    service = WorkspaceService(WorkspaceConfigStore(tmp_path / "workspace.json"))

    status = apply_workspace_override(service, {"VOICE_ACP_WORKSPACE": str(project)})

    assert status.state == "ready"
    assert service.status() == status
    assert status.workspace is not None
    assert status.workspace.primary_directory == str(project.resolve())


def test_workspace_override_cannot_bypass_absolute_directory_validation(
    tmp_path, monkeypatch
):
    project = tmp_path / "project"
    project.mkdir()
    monkeypatch.chdir(tmp_path)
    service = WorkspaceService(WorkspaceConfigStore(tmp_path / "workspace.json"))

    with pytest.raises(ValueError, match="absolute existing directory"):
        apply_workspace_override(service, {"VOICE_ACP_WORKSPACE": "project"})

    assert service.status().state == "unconfigured"
