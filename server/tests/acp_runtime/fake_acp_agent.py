"""A deterministic ACP agent process used only by the ACP runtime tests."""

import asyncio
import sys
from dataclasses import dataclass
from pathlib import Path

import acp
from acp.schema import AuthMethodAgent


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
    ) -> None:
        self.record_path = record_path
        self.advertises_chatgpt = advertises_chatgpt
        self.requires_authentication = requires_authentication
        self.authentication_fails = authentication_fails
        self.session_fails_after_authentication = session_fails_after_authentication
        self.authenticated = False

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


@dataclass(frozen=True)
class FakeAcpAgentProcess:
    record_path: Path
    advertises_chatgpt: bool = False
    requires_authentication: bool = False
    authentication_fails: bool = False
    session_fails_after_authentication: bool = False

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
) -> None:
    agent = FakeAcpAgent(
        record_path,
        advertises_chatgpt,
        requires_authentication,
        authentication_fails,
        session_fails_after_authentication,
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
    asyncio.run(
        _serve(
            record_path,
            advertises_chatgpt,
            requires_authentication,
            authentication_fails,
            session_fails_after_authentication,
        )
    )


if __name__ == "__main__":
    main()
