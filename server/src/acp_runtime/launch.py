"""Explicit, non-secret local runtime launch overrides."""

from typing import Mapping

from .workspace import WorkspaceService, WorkspaceStatus


def apply_workspace_override(
    service: WorkspaceService, values: Mapping[str, str]
) -> WorkspaceStatus:
    """Apply --workspace through the same validated selection path as Settings."""
    workspace = values.get("VOICE_ACP_WORKSPACE")
    return service.select(workspace) if workspace else service.status()
