"""Background native Project Folder browse operation tests."""

import asyncio

import pytest

from acp_runtime.browse import (
    BrowseAlreadyActive,
    BrowseOperationNotFound,
    WorkspaceBrowseCoordinator,
)
from acp_runtime.workspace import CODEX_PROFILE, WorkspaceScope, WorkspaceStatus


class BlockingPicker:
    def __init__(self) -> None:
        self._result: asyncio.Future[str | None] | None = None

    async def pick(self) -> str | None:
        self._result = asyncio.get_running_loop().create_future()
        return await self._result

    async def wait_until_open(self) -> None:
        while self._result is None:
            await asyncio.sleep(0)

    def complete(self, path: str | None) -> None:
        assert self._result is not None
        self._result.set_result(path)


def ready_workspace(path: str) -> WorkspaceStatus:
    return WorkspaceStatus(
        state="ready",
        profile=CODEX_PROFILE,
        workspace=WorkspaceScope(
            id="workspace-a",
            label="project",
            primary_directory=path,
        ),
    )


@pytest.mark.anyio
async def test_start_returns_while_picker_is_still_waiting(tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    picker = BlockingPicker()

    async def select_workspace(path: str) -> WorkspaceStatus:
        return ready_workspace(path)

    coordinator = WorkspaceBrowseCoordinator(picker, select_workspace)

    started = coordinator.start()
    await picker.wait_until_open()

    assert started.state == "picking"
    assert coordinator.status(started.operation_id).state == "picking"

    picker.complete(str(project))
    completed = await coordinator.wait(started.operation_id)

    assert completed.state == "ready"
    assert completed.workspace == ready_workspace(str(project))


@pytest.mark.anyio
async def test_cancelled_picker_is_a_terminal_operation():
    picker = BlockingPicker()

    async def select_workspace(_path: str) -> WorkspaceStatus:
        raise AssertionError("cancelled picker must not select a Workspace")

    coordinator = WorkspaceBrowseCoordinator(picker, select_workspace)
    started = coordinator.start()
    await picker.wait_until_open()

    picker.complete(None)
    completed = await coordinator.wait(started.operation_id)

    assert completed.state == "cancelled"
    assert completed.workspace is None
    assert completed.error == "Project Folder selection was cancelled"


@pytest.mark.anyio
async def test_only_one_picker_operation_can_be_active():
    picker = BlockingPicker()

    async def select_workspace(path: str) -> WorkspaceStatus:
        return ready_workspace(path)

    coordinator = WorkspaceBrowseCoordinator(picker, select_workspace)
    started = coordinator.start()
    await picker.wait_until_open()

    with pytest.raises(BrowseAlreadyActive, match="already open"):
        coordinator.start()

    picker.complete(None)
    await coordinator.wait(started.operation_id)


def test_unknown_operation_id_is_rejected():
    picker = BlockingPicker()

    async def select_workspace(path: str) -> WorkspaceStatus:
        return ready_workspace(path)

    coordinator = WorkspaceBrowseCoordinator(picker, select_workspace)

    with pytest.raises(BrowseOperationNotFound, match="not found"):
        coordinator.status("missing")
