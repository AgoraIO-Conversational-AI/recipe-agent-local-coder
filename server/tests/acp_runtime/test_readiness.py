"""Local ACP readiness tests through the coordinator's public seam."""

import pytest

from acp_runtime.acp_client import AcpSession
from acp_runtime.readiness import LocalRuntimeCoordinator
from acp_runtime.workspace import WorkspaceConfigStore, WorkspaceService


class FakeAcpClient:
    """In-memory ACP seam; these tests never start a subprocess."""

    def __init__(self) -> None:
        self.opened: list[str] = []
        self.events: list[tuple[str, str | None]] = []
        self.close_calls = 0
        self.open_error: Exception | None = None

    async def open(self, primary_directory: str) -> AcpSession:
        self.opened.append(primary_directory)
        self.events.append(("open", primary_directory))
        if self.open_error is not None:
            raise self.open_error
        return AcpSession(primary_directory=primary_directory)

    async def close(self) -> None:
        self.close_calls += 1
        self.events.append(("close", None))


@pytest.fixture
def unconfigured(tmp_path):
    return WorkspaceService(WorkspaceConfigStore(tmp_path / "workspace.json"))


@pytest.fixture
def ready(unconfigured, tmp_path):
    project = tmp_path / "project"
    project.mkdir()
    unconfigured.select(str(project))
    return unconfigured


@pytest.fixture
def fake_acp():
    return FakeAcpClient()


@pytest.mark.anyio
async def test_runtime_requires_workspace_before_starting_acp(unconfigured, fake_acp):
    runtime = LocalRuntimeCoordinator(unconfigured, fake_acp)
    assert (await runtime.start()).state == "configuration_required"
    assert fake_acp.opened == []


@pytest.mark.anyio
async def test_selecting_workspace_opens_exactly_one_persistent_session(ready, fake_acp):
    runtime = LocalRuntimeCoordinator(ready, fake_acp)
    assert (await runtime.start()).state == "ready"
    assert fake_acp.opened == [ready.status().workspace.primary_directory]
    assert (await runtime.start()).state == "ready"
    assert len(fake_acp.opened) == 1


@pytest.mark.anyio
async def test_changing_workspace_closes_the_old_session_before_opening_the_new_one(
    ready, fake_acp, tmp_path
):
    runtime = LocalRuntimeCoordinator(ready, fake_acp)
    await runtime.start()
    next_project = tmp_path / "next-project"
    next_project.mkdir()
    ready.select(str(next_project))

    status = await runtime.activate_workspace()

    assert status.state == "ready"
    assert fake_acp.close_calls == 1
    assert fake_acp.opened == [
        str(tmp_path / "project"),
        str(next_project),
    ]
    assert fake_acp.events == [
        ("open", str(tmp_path / "project")),
        ("close", None),
        ("open", str(next_project)),
    ]


@pytest.mark.anyio
async def test_authentication_failures_return_an_actionable_local_state(ready, fake_acp):
    fake_acp.open_error = RuntimeError("ChatGPT authentication required")
    runtime = LocalRuntimeCoordinator(ready, fake_acp)

    status = await runtime.start()

    assert status.state == "authentication_required"
    assert status.error == "Sign in to ChatGPT, then retry the local Codex runtime."


@pytest.mark.anyio
async def test_other_acp_failures_return_an_actionable_local_state(ready, fake_acp):
    fake_acp.open_error = RuntimeError("missing executable")
    runtime = LocalRuntimeCoordinator(ready, fake_acp)

    status = await runtime.start()

    assert status.state == "failed"
    assert status.error == "Could not start the local Codex runtime: missing executable"
