"""ACP process/session lifecycle tests through the runtime's public boundary."""

import pytest

from acp_runtime.codex import CodexAcpClient, CodexCommand
from tests.acp_runtime.fake_acp_agent import FakeAcpAgentProcess


@pytest.fixture
def project(tmp_path):
    directory = tmp_path / "project"
    directory.mkdir()
    return directory


@pytest.fixture
def fake_agent(tmp_path):
    return FakeAcpAgentProcess(tmp_path / "acp-requests.txt")


def test_default_codex_command_is_pinned_and_needs_no_global_install():
    assert CodexCommand.default().argv == (
        "npx",
        "-y",
        "@agentclientprotocol/codex-acp@1.1.7",
    )
    assert CodexCommand.default().env["INITIAL_AGENT_MODE"] == "agent"


@pytest.mark.anyio
async def test_client_initializes_and_creates_session_in_project_folder(
    fake_agent, project
):
    client = CodexAcpClient(command=fake_agent.command)

    session = await client.open(str(project))

    assert session.primary_directory == str(project.resolve())
    assert fake_agent.requests == ["initialize", "session/new"]

    await client.close()

    assert fake_agent.requests[-1] == "process/exited"
    assert fake_agent.process_exited


@pytest.mark.anyio
async def test_client_uses_advertised_chatgpt_authentication_only_when_required(
    tmp_path, project
):
    fake_agent = FakeAcpAgentProcess(
        tmp_path / "acp-auth-requests.txt", requires_authentication=True
    )
    client = CodexAcpClient(command=fake_agent.command)

    await client.open(str(project))

    assert fake_agent.requests == ["initialize", "authenticate", "session/new"]
    await client.close()
