"""ACP process/session lifecycle tests through the runtime's public boundary."""

import json
from types import SimpleNamespace

import acp
import pytest

from acp_runtime.acp_client import AcpAuthenticationRequired
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


def test_environment_overrides_preserve_agent_mode_and_pass_only_supported_auth(
    monkeypatch,
):
    monkeypatch.setenv("INITIAL_AGENT_MODE", "agent-full-access")
    monkeypatch.setenv("CODEX_PATH", "/opt/codex/bin/codex")
    monkeypatch.setenv("CODEX_API_KEY", "codex-test-secret")
    monkeypatch.setenv("OPENAI_API_KEY", "openai-test-secret")

    command = CodexCommand.from_environment()

    assert command.argv == CodexCommand.default().argv
    assert command.env == {
        "INITIAL_AGENT_MODE": "agent",
        "CODEX_PATH": "/opt/codex/bin/codex",
        "CODEX_API_KEY": "codex-test-secret",
        "OPENAI_API_KEY": "openai-test-secret",
    }


def test_custom_acp_command_is_a_json_argv_array_never_a_shell_string(monkeypatch):
    monkeypatch.setenv(
        "VOICE_ACP_COMMAND_JSON",
        json.dumps(["/opt/acp/bin/custom-agent", "--stdio", "value with spaces"]),
    )

    command = CodexCommand.from_environment()

    assert command.argv == (
        "/opt/acp/bin/custom-agent",
        "--stdio",
        "value with spaces",
    )
    assert command.env["INITIAL_AGENT_MODE"] == "agent"


@pytest.mark.parametrize(
    "value",
    ["not-json", '"shell string"', "[]", '["valid", 3]'],
)
def test_invalid_custom_acp_command_fails_with_a_fixed_safe_message(monkeypatch, value):
    monkeypatch.setenv("VOICE_ACP_COMMAND_JSON", value)

    with pytest.raises(ValueError) as raised:
        CodexCommand.from_environment()

    assert str(raised.value) == (
        "VOICE_ACP_COMMAND_JSON must be a JSON array of non-empty argument strings"
    )
    assert value not in str(raised.value)


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
async def test_close_treats_an_already_closed_transport_as_success(
    monkeypatch, project
):
    class ClosedTransportConnection:
        async def initialize(self, **_kwargs):
            return SimpleNamespace(auth_methods=[])

        async def new_session(self, **_kwargs):
            return SimpleNamespace(session_id="closed-session")

        async def close_session(self, _session_id):
            raise ConnectionError("Connection closed")

    class ProcessContext:
        def __init__(self):
            self.exited = False

        async def __aenter__(self):
            return ClosedTransportConnection(), object()

        async def __aexit__(self, *_args):
            self.exited = True

    process = ProcessContext()
    monkeypatch.setattr(
        "acp_runtime.codex.acp.spawn_agent_process",
        lambda *_args, **_kwargs: process,
    )
    client = CodexAcpClient(command=("fake-acp",))
    await client.open(str(project))

    await client.close()
    await client.close()

    assert process.exited


@pytest.mark.anyio
async def test_client_reuses_saved_auth_before_trying_advertised_chatgpt(
    tmp_path, project
):
    fake_agent = FakeAcpAgentProcess(
        tmp_path / "acp-saved-auth-requests.txt", advertises_chatgpt=True
    )
    client = CodexAcpClient(command=fake_agent.command)

    await client.open(str(project))

    assert fake_agent.requests == ["initialize", "session/new"]
    await client.close()


@pytest.mark.anyio
async def test_client_authenticates_only_after_typed_auth_required_then_retries_once(
    tmp_path, project
):
    fake_agent = FakeAcpAgentProcess(
        tmp_path / "acp-auth-requests.txt",
        advertises_chatgpt=True,
        requires_authentication=True,
    )
    client = CodexAcpClient(command=fake_agent.command)

    await client.open(str(project))

    assert fake_agent.requests == [
        "initialize",
        "session/new",
        "authenticate",
        "session/new",
    ]
    await client.close()


@pytest.mark.anyio
async def test_client_exposes_authentication_failure_as_typed_boundary_result(
    tmp_path, project
):
    fake_agent = FakeAcpAgentProcess(
        tmp_path / "acp-auth-failure-requests.txt",
        advertises_chatgpt=True,
        requires_authentication=True,
        authentication_fails=True,
    )
    client = CodexAcpClient(command=fake_agent.command)

    with pytest.raises(AcpAuthenticationRequired):
        await client.open(str(project))

    assert fake_agent.requests == [
        "initialize",
        "session/new",
        "authenticate",
        "process/exited",
    ]


@pytest.mark.anyio
async def test_client_does_not_relabel_post_auth_session_failure(tmp_path, project):
    fake_agent = FakeAcpAgentProcess(
        tmp_path / "acp-post-auth-session-failure.txt",
        advertises_chatgpt=True,
        requires_authentication=True,
        session_fails_after_authentication=True,
    )
    client = CodexAcpClient(command=fake_agent.command)

    with pytest.raises(acp.RequestError) as raised:
        await client.open(str(project))

    assert raised.value.code == -32603
    assert fake_agent.requests == [
        "initialize",
        "session/new",
        "authenticate",
        "session/new",
        "process/exited",
    ]


@pytest.mark.anyio
async def test_client_does_not_guess_an_unadvertised_authentication_method(
    tmp_path, project
):
    fake_agent = FakeAcpAgentProcess(
        tmp_path / "acp-unadvertised-auth.txt",
        requires_authentication=True,
    )
    client = CodexAcpClient(command=fake_agent.command)

    with pytest.raises(AcpAuthenticationRequired):
        await client.open(str(project))

    assert fake_agent.requests == ["initialize", "session/new", "process/exited"]
