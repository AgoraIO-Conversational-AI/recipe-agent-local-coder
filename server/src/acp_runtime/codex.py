"""Codex-specific ACP process and session lifecycle."""

import sys
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

import acp
from acp.schema import DeniedOutcome

from .acp_client import AcpPermissionRequest, AcpSession, AcpSessionEvent


_MAX_PERMISSION_OPERATION_BYTES = 160
_MAX_PERMISSION_OPTION_BYTES = 96
_MAX_PERMISSION_OPTIONS = 8


@dataclass(frozen=True)
class CodexCommand:
    """The pinned, on-demand Codex ACP command and its narrow override env."""

    argv: tuple[str, ...]
    env: Mapping[str, str]

    @classmethod
    def default(cls) -> "CodexCommand":
        return cls(
            argv=("npx", "-y", "@agentclientprotocol/codex-acp@1.1.7"),
            env={"INITIAL_AGENT_MODE": "agent"},
        )


class _AcpCallback:
    """Collect only safe ACP callback summaries and deny permissions by default."""

    def __init__(self) -> None:
        self.events: list[AcpSessionEvent] = []
        self.permission_requests: list[AcpPermissionRequest] = []

    async def session_update(self, session_id: str, update: object, **_kwargs: Any) -> None:
        del session_id
        self.events.append(AcpSessionEvent(kind=type(update).__name__))

    async def request_permission(
        self, session_id: str, tool_call: object, options: list[object], **_kwargs: Any
    ) -> acp.RequestPermissionResponse:
        del session_id
        operation = _bounded_text(
            str(getattr(tool_call, "title", None) or type(tool_call).__name__),
            _MAX_PERMISSION_OPERATION_BYTES,
        )
        self.permission_requests.append(
            AcpPermissionRequest(
                operation=operation,
                options=tuple(
                    _bounded_text(str(getattr(option, "name", "")), _MAX_PERMISSION_OPTION_BYTES)
                    for option in options[:_MAX_PERMISSION_OPTIONS]
                ),
            )
        )
        return acp.RequestPermissionResponse(
            outcome=DeniedOutcome(outcome="cancelled")
        )


class CodexAcpClient:
    """Own one local Codex ACP child process and one session at a time."""

    def __init__(self, command: CodexCommand | Sequence[str] | None = None) -> None:
        resolved_command = command or CodexCommand.default()
        if isinstance(resolved_command, CodexCommand):
            self._argv = resolved_command.argv
            self._env = dict(resolved_command.env)
        else:
            self._argv = tuple(resolved_command)
            self._env = {}
        if not self._argv:
            raise ValueError("Codex ACP command cannot be empty")

        self._callback = _AcpCallback()
        self._process_context: AbstractAsyncContextManager[tuple[Any, Any]] | None = None
        self._connection: Any | None = None
        self._session_id: str | None = None
        self._session: AcpSession | None = None

    @property
    def events(self) -> tuple[AcpSessionEvent, ...]:
        """Safe event summaries received from the active ACP session."""
        return tuple(self._callback.events)

    @property
    def permission_requests(self) -> tuple[AcpPermissionRequest, ...]:
        """Bounded permission prompts that always require an explicit future decision."""
        return tuple(self._callback.permission_requests)

    async def open(self, primary_directory: str) -> AcpSession:
        """Start ACP v1 and create one session scoped to an existing absolute folder."""
        if self._session is not None:
            raise RuntimeError("An ACP session is already open")
        resolved_path = _resolve_project_folder(primary_directory)
        process_context = acp.spawn_agent_process(
            self._callback,
            self._argv[0],
            *self._argv[1:],
            env=self._env,
            cwd=resolved_path,
        )
        connection: Any | None = None
        try:
            connection, _process = await process_context.__aenter__()
            initialized = await connection.initialize(protocol_version=acp.PROTOCOL_VERSION)
            chatgpt_method = _advertised_chatgpt_method(initialized.auth_methods)
            if chatgpt_method is not None:
                await connection.authenticate(chatgpt_method)
            new_session = await connection.new_session(
                cwd=resolved_path,
                mcp_servers=[],
            )
        except BaseException:
            if connection is not None:
                await process_context.__aexit__(*sys.exc_info())
            raise

        self._process_context = process_context
        self._connection = connection
        self._session_id = new_session.session_id
        self._session = AcpSession(primary_directory=resolved_path)
        return self._session

    async def close(self) -> None:
        """Close the session and subprocess once; repeated closes are no-ops."""
        process_context = self._process_context
        connection = self._connection
        session_id = self._session_id
        self._process_context = None
        self._connection = None
        self._session_id = None
        self._session = None

        if process_context is None:
            return
        try:
            if connection is not None and session_id is not None:
                await connection.close_session(session_id)
        finally:
            await process_context.__aexit__(None, None, None)


def _resolve_project_folder(primary_directory: str) -> str:
    path = Path(primary_directory)
    if not path.is_absolute():
        raise ValueError("Project Folder must be an absolute existing directory")
    try:
        resolved = path.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise ValueError("Project Folder must be an absolute existing directory") from exc
    if not resolved.is_dir():
        raise ValueError("Project Folder must be an absolute existing directory")
    return str(resolved)


def _advertised_chatgpt_method(auth_methods: object) -> str | None:
    if not auth_methods:
        return None
    for method in auth_methods:
        method_id = getattr(method, "id", "")
        method_name = getattr(method, "name", "")
        if str(method_id).casefold() == "chatgpt" or str(method_name).casefold() == "chatgpt":
            return str(method_id)
    return None


def _bounded_text(value: str, max_bytes: int) -> str:
    normalized = " ".join(value.split())
    return normalized.encode("utf-8")[:max_bytes].decode("utf-8", errors="ignore")
