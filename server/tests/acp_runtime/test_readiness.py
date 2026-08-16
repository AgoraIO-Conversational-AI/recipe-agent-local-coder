"""Local ACP readiness tests through the coordinator's public seam."""

import asyncio

import pytest

from acp_runtime.acp_client import AcpAuthenticationRequired, AcpSession
from acp_runtime.readiness import LocalRuntimeCoordinator
from acp_runtime.workspace import WorkspaceConfigStore, WorkspaceService


class FakeAcpClient:
    """In-memory ACP seam; these tests never start a subprocess."""

    def __init__(self) -> None:
        self.opened: list[str] = []
        self.events: list[tuple[str, str | None]] = []
        self.close_calls = 0
        self.open_error: Exception | None = None
        self.open_started = asyncio.Event()
        self.release_open = asyncio.Event()
        self.block_open = False

    async def open(self, primary_directory: str) -> AcpSession:
        self.opened.append(primary_directory)
        self.events.append(("open", primary_directory))
        self.open_started.set()
        if self.block_open:
            await self.release_open.wait()
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
    fake_acp.open_error = AcpAuthenticationRequired()
    runtime = LocalRuntimeCoordinator(ready, fake_acp)

    status = await runtime.start()

    assert status.state == "authentication_required"
    assert status.error == "Sign in to ChatGPT, then retry the local Codex runtime."


@pytest.mark.anyio
async def test_other_acp_failures_return_an_actionable_local_state(ready, fake_acp):
    fake_acp.open_error = RuntimeError(
        "missing executable for /Users/private/project with OPENAI_API_KEY=secret"
    )
    runtime = LocalRuntimeCoordinator(ready, fake_acp)

    status = await runtime.start()

    assert status.state == "failed"
    assert status.error == (
        "Could not start the local Codex runtime. Check the local runtime setup and retry."
    )
    assert "private" not in status.error
    assert "secret" not in status.error


@pytest.mark.anyio
async def test_concurrent_starts_open_only_one_persistent_session(ready, fake_acp):
    fake_acp.block_open = True
    runtime = LocalRuntimeCoordinator(ready, fake_acp)

    first_start = asyncio.create_task(runtime.start())
    await fake_acp.open_started.wait()
    second_start = asyncio.create_task(runtime.start())
    await asyncio.sleep(0)

    assert fake_acp.opened == [ready.status().workspace.primary_directory]
    fake_acp.release_open.set()
    first_status, second_status = await asyncio.gather(first_start, second_start)

    assert first_status.state == second_status.state == "ready"
    assert len(fake_acp.opened) == 1


@pytest.mark.anyio
async def test_concurrent_replacements_close_then_open_each_workspace_once(
    ready, fake_acp, tmp_path
):
    runtime = LocalRuntimeCoordinator(ready, fake_acp)
    await runtime.start()
    second_project = tmp_path / "second-project"
    third_project = tmp_path / "third-project"
    second_project.mkdir()
    third_project.mkdir()
    ready.select(str(second_project))
    fake_acp.block_open = True
    fake_acp.open_started.clear()
    first_replace = asyncio.create_task(runtime.activate_workspace())
    await fake_acp.open_started.wait()
    ready.select(str(third_project))
    second_replace = asyncio.create_task(runtime.activate_workspace())
    await asyncio.sleep(0)

    assert fake_acp.events == [
        ("open", str(tmp_path / "project")),
        ("close", None),
        ("open", str(second_project)),
    ]
    fake_acp.release_open.set()
    await asyncio.gather(first_replace, second_replace)

    assert fake_acp.events == [
        ("open", str(tmp_path / "project")),
        ("close", None),
        ("open", str(second_project)),
        ("close", None),
        ("open", str(third_project)),
    ]
    assert runtime.status().state == "ready"


@pytest.mark.anyio
async def test_close_waits_for_an_inflight_open_then_closes_the_new_session(ready, fake_acp):
    fake_acp.block_open = True
    runtime = LocalRuntimeCoordinator(ready, fake_acp)

    start = asyncio.create_task(runtime.start())
    await fake_acp.open_started.wait()
    close = asyncio.create_task(runtime.close())
    await asyncio.sleep(0)

    assert fake_acp.close_calls == 0
    fake_acp.release_open.set()
    await asyncio.gather(start, close)

    assert fake_acp.close_calls == 1
    assert runtime.status().state == "starting"
