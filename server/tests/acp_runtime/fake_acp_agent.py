"""A deterministic ACP agent process used only by the ACP runtime tests."""

import asyncio
import base64
import sys
from dataclasses import dataclass
from pathlib import Path

import acp
from acp.schema import (
    AgentMessageChunk,
    AgentThoughtChunk,
    AuthMethodAgent,
    PermissionOption,
    TextContentBlock,
    ToolCallStart,
    ToolCallUpdate,
)


def _record(path: Path, request: str) -> None:
    with path.open("a", encoding="utf-8") as stream:
        stream.write(f"{request}\n")


class FakeAcpAgent:
    def __init__(
        self,
        record_path: Path,
        advertises_chatgpt: bool,
        requires_authentication: bool,
        authentication_fails: bool,
        session_fails_after_authentication: bool,
        prompt_result: str | None,
        requests_permission: bool,
        blocks_until_cancel: bool,
    ) -> None:
        self.record_path = record_path
        self.advertises_chatgpt = advertises_chatgpt
        self.requires_authentication = requires_authentication
        self.authentication_fails = authentication_fails
        self.session_fails_after_authentication = session_fails_after_authentication
        self.prompt_result = prompt_result
        self.requests_permission = requests_permission
        self.blocks_until_cancel = blocks_until_cancel
        self.authenticated = False
        self.client = None
        self.cancelled = asyncio.Event()

    def on_connect(self, client) -> None:
        self.client = client

    async def initialize(self, protocol_version: int, **_kwargs):
        _record(self.record_path, "initialize")
        methods = (
            [AuthMethodAgent(id="chatgpt", name="ChatGPT")]
            if self.advertises_chatgpt
            else []
        )
        return acp.InitializeResponse(
            protocol_version=protocol_version,
            auth_methods=methods,
        )

    async def authenticate(self, method_id: str, **_kwargs):
        if method_id != "chatgpt":
            raise ValueError("unexpected authentication method")
        _record(self.record_path, "authenticate")
        if self.authentication_fails:
            raise RuntimeError("fake authentication failure")
        self.authenticated = True
        return acp.AuthenticateResponse()

    async def new_session(self, cwd: str, mcp_servers, **_kwargs):
        if not Path(cwd).is_absolute() or mcp_servers != []:
            raise ValueError("session must use one absolute folder and no MCP servers")
        _record(self.record_path, "session/new")
        if self.requires_authentication and not self.authenticated:
            raise acp.RequestError.auth_required()
        if self.session_fails_after_authentication and self.authenticated:
            raise acp.RequestError.internal_error()
        return acp.NewSessionResponse(session_id="fake-session")

    async def close_session(self, session_id: str, **_kwargs):
        if session_id != "fake-session":
            raise ValueError("unexpected session")
        _record(self.record_path, "session/close")

    async def prompt(self, session_id: str, prompt, **_kwargs):
        if session_id != "fake-session" or not prompt:
            raise ValueError("unexpected prompt")
        _record(self.record_path, "session/prompt")
        if self.blocks_until_cancel:
            await self.cancelled.wait()
            return acp.PromptResponse(stop_reason="cancelled")
        if self.client is None:
            raise RuntimeError("fake ACP client is not connected")
        await self.client.session_update(
            session_id,
            ToolCallStart(
                session_update="tool_call",
                tool_call_id="tool-1",
                title="Run tests with SECRET=value",
                kind="execute",
            ),
        )
        await self.client.session_update(
            session_id,
            AgentThoughtChunk(
                session_update="agent_thought_chunk",
                content=TextContentBlock(type="text", text="private reasoning"),
            ),
        )
        if self.requests_permission:
            response = await self.client.request_permission(
                session_id,
                ToolCallUpdate(
                    tool_call_id="tool-1",
                    title="Run command containing SECRET=value",
                    kind="execute",
                ),
                [
                    PermissionOption(
                        option_id="allow-once",
                        name="Allow once",
                        kind="allow_once",
                    ),
                    PermissionOption(
                        option_id="allow-always",
                        name="Always allow",
                        kind="allow_always",
                    ),
                    PermissionOption(
                        option_id="reject-once",
                        name="Reject once",
                        kind="reject_once",
                    ),
                ],
            )
            if response.outcome.outcome == "selected":
                _record(
                    self.record_path,
                    f"permission/selected:{response.outcome.option_id}",
                )
            else:
                _record(self.record_path, "permission/cancelled")
        final_text = self.prompt_result or "Completed."
        await self.client.session_update(
            session_id,
            AgentMessageChunk(
                session_update="agent_message_chunk",
                content=TextContentBlock(type="text", text=final_text),
            ),
        )
        return acp.PromptResponse(stop_reason="end_turn")

    async def cancel(self, session_id: str, **_kwargs):
        if session_id != "fake-session":
            raise ValueError("unexpected session")
        _record(self.record_path, "session/cancel")
        self.cancelled.set()


@dataclass(frozen=True)
class FakeAcpAgentProcess:
    record_path: Path
    advertises_chatgpt: bool = False
    requires_authentication: bool = False
    authentication_fails: bool = False
    session_fails_after_authentication: bool = False
    prompt_result: str | None = None
    requests_permission: bool = False
    blocks_until_cancel: bool = False

    @property
    def command(self) -> tuple[str, ...]:
        command = (sys.executable, str(Path(__file__)), str(self.record_path))
        if self.advertises_chatgpt:
            command = (*command, "--advertises-chatgpt")
        if self.requires_authentication:
            command = (*command, "--requires-authentication")
        if self.authentication_fails:
            command = (*command, "--authentication-fails")
        if self.session_fails_after_authentication:
            command = (*command, "--session-fails-after-authentication")
        if self.prompt_result is not None:
            encoded = base64.urlsafe_b64encode(self.prompt_result.encode()).decode()
            command = (*command, "--prompt-result-base64", encoded)
        if self.requests_permission:
            command = (*command, "--requests-permission")
        if self.blocks_until_cancel:
            command = (*command, "--blocks-until-cancel")
        return command

    @property
    def requests(self) -> list[str]:
        if not self.record_path.exists():
            return []
        return self.record_path.read_text(encoding="utf-8").splitlines()

    @property
    def process_exited(self) -> bool:
        return "process/exited" in self.requests


async def _serve(
    record_path: Path,
    advertises_chatgpt: bool,
    requires_authentication: bool,
    authentication_fails: bool,
    session_fails_after_authentication: bool,
    prompt_result: str | None,
    requests_permission: bool,
    blocks_until_cancel: bool,
) -> None:
    agent = FakeAcpAgent(
        record_path,
        advertises_chatgpt,
        requires_authentication,
        authentication_fails,
        session_fails_after_authentication,
        prompt_result,
        requests_permission,
        blocks_until_cancel,
    )
    try:
        await acp.run_agent(agent, use_unstable_protocol=True)
    finally:
        _record(record_path, "process/exited")


def main() -> None:
    record_path = Path(sys.argv[1])
    advertises_chatgpt = "--advertises-chatgpt" in sys.argv[2:]
    requires_authentication = "--requires-authentication" in sys.argv[2:]
    authentication_fails = "--authentication-fails" in sys.argv[2:]
    session_fails_after_authentication = (
        "--session-fails-after-authentication" in sys.argv[2:]
    )
    prompt_result = None
    if "--prompt-result-base64" in sys.argv[2:]:
        index = sys.argv.index("--prompt-result-base64")
        prompt_result = base64.urlsafe_b64decode(sys.argv[index + 1]).decode()
    requests_permission = "--requests-permission" in sys.argv[2:]
    blocks_until_cancel = "--blocks-until-cancel" in sys.argv[2:]
    asyncio.run(
        _serve(
            record_path,
            advertises_chatgpt,
            requires_authentication,
            authentication_fails,
            session_fails_after_authentication,
            prompt_result,
            requests_permission,
            blocks_until_cancel,
        )
    )


if __name__ == "__main__":
    main()
