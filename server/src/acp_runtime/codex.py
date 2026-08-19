"""Codex-specific ACP process and session lifecycle."""

import asyncio
import json
import os
import secrets
import sys
from contextlib import AbstractAsyncContextManager
from dataclasses import dataclass
from typing import Any, Mapping, Sequence

import acp
from acp.schema import (
    AgentMessageChunk,
    AllowedOutcome,
    DeniedOutcome,
    TextContentBlock,
    ToolCallProgress,
    ToolCallStart,
)

from .acp_client import (
    AcpAuthenticationRequired,
    AcpPermissionOption,
    AcpPermissionRequest,
    AcpPromptObserver,
    AcpPromptResult,
    AcpSession,
    AcpSessionEvent,
)
from .workspace import resolve_project_folder


_MAX_PERMISSION_OPTION_BYTES = 96
_MAX_PERMISSION_OPTIONS = 8
_CUSTOM_COMMAND_ERROR = (
    "VOICE_ACP_COMMAND_JSON must be a JSON array of non-empty argument strings"
)


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

    @classmethod
    def from_environment(
        cls, environ: Mapping[str, str] | None = None
    ) -> "CodexCommand":
        """Build the advanced launch contract without shell parsing or full access."""
        values = os.environ if environ is None else environ
        command = cls.default()
        raw_override = values.get("VOICE_ACP_COMMAND_JSON")
        if raw_override:
            try:
                parsed = json.loads(raw_override)
            except (TypeError, json.JSONDecodeError) as exc:
                raise ValueError(_CUSTOM_COMMAND_ERROR) from exc
            if (
                not isinstance(parsed, list)
                or not parsed
                or len(parsed) > 64
                or any(
                    not isinstance(argument, str)
                    or not argument.strip()
                    or len(argument.encode("utf-8")) > 4096
                    for argument in parsed
                )
            ):
                raise ValueError(_CUSTOM_COMMAND_ERROR)
            command = cls(argv=tuple(parsed), env=command.env)

        child_env = {"INITIAL_AGENT_MODE": "agent"}
        for name in ("CODEX_PATH", "CODEX_API_KEY", "OPENAI_API_KEY"):
            value = values.get(name)
            if value:
                child_env[name] = value
        return cls(argv=command.argv, env=child_env)


class _AcpCallback:
    """Project active prompt callbacks into bounded backend-neutral values."""

    def __init__(self) -> None:
        self.events: list[AcpSessionEvent] = []
        self.permission_requests: list[AcpPermissionRequest] = []
        self._observer: AcpPromptObserver | None = None
        self._session_id: str | None = None
        self._message_chunks: list[str] = []

    def activate(self, session_id: str, observer: AcpPromptObserver) -> None:
        self._observer = observer
        self._session_id = session_id
        self._message_chunks = []

    def deactivate(self) -> str:
        final_text = "".join(self._message_chunks).strip()
        self._observer = None
        self._session_id = None
        self._message_chunks = []
        return final_text

    async def settle_messages(self) -> None:
        """Let notifications sent before the prompt response finish dispatching."""
        previous_size = len(self._message_chunks)
        stable_checks = 0
        for _ in range(10):
            await asyncio.sleep(0.01)
            current_size = len(self._message_chunks)
            if current_size == previous_size:
                stable_checks += 1
                if stable_checks >= 2:
                    return
            else:
                stable_checks = 0
            previous_size = current_size

    async def session_update(self, session_id: str, update: object, **_kwargs: Any) -> None:
        observer = self._observer
        if observer is None or session_id != self._session_id:
            return
        if isinstance(update, AgentMessageChunk) and isinstance(
            update.content, TextContentBlock
        ):
            self._message_chunks.append(update.content.text)
            if len("".join(self._message_chunks).encode("utf-8")) > 256 * 1024:
                raise RuntimeError("ACP prompt response exceeded the local result limit")
            return
        if not isinstance(update, (ToolCallStart, ToolCallProgress)):
            return
        kind = str(update.kind or "other")
        event = AcpSessionEvent(kind=kind, label=_activity_label(kind))
        self.events.append(event)
        await observer.on_event(event)

    async def request_permission(
        self, session_id: str, tool_call: object, options: list[object], **_kwargs: Any
    ) -> acp.RequestPermissionResponse:
        observer = self._observer
        if observer is None or session_id != self._session_id:
            return acp.RequestPermissionResponse(
                outcome=DeniedOutcome(outcome="cancelled")
            )
        kind = str(getattr(tool_call, "kind", None) or "other")
        permission_options = tuple(
            AcpPermissionOption(
                option_id=_bounded_text(
                    str(getattr(option, "option_id", "")),
                    _MAX_PERMISSION_OPTION_BYTES,
                ),
                name=_permission_name(str(getattr(option, "kind", ""))),
                kind=getattr(option, "kind"),
            )
            for option in options[:_MAX_PERMISSION_OPTIONS]
            if getattr(option, "kind", None)
            in {"allow_once", "allow_always", "reject_once", "reject_always"}
            and getattr(option, "option_id", None)
        )
        request = AcpPermissionRequest(
            authorization_id=secrets.token_urlsafe(18),
            operation=_permission_operation(kind),
            options=permission_options,
        )
        self.permission_requests.append(request)
        outcome = await observer.request_permission(request)
        allowed_ids = {option.option_id for option in permission_options}
        if outcome.option_id is not None and outcome.option_id in allowed_ids:
            return acp.RequestPermissionResponse(
                outcome=AllowedOutcome(
                    outcome="selected", option_id=outcome.option_id
                )
            )
        return acp.RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))


class CodexAcpClient:
    """Own one local Codex ACP child process and one session at a time."""

    def __init__(self, command: CodexCommand | Sequence[str] | None = None) -> None:
        resolved_command = command or CodexCommand.from_environment()
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
        self._prompt_lock = asyncio.Lock()

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
        resolved_path = resolve_project_folder(primary_directory)
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
            try:
                new_session = await connection.new_session(
                    cwd=resolved_path,
                    mcp_servers=[],
                )
            except acp.RequestError as exc:
                if exc.code != -32000:
                    raise
                if chatgpt_method is None:
                    raise AcpAuthenticationRequired() from exc
                try:
                    await connection.authenticate(chatgpt_method)
                except Exception as auth_exc:
                    raise AcpAuthenticationRequired() from auth_exc
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

    async def prompt(
        self, objective: str, observer: AcpPromptObserver
    ) -> AcpPromptResult:
        """Send one objective through the active session and collect its safe result."""
        connection = self._connection
        session_id = self._session_id
        if connection is None or session_id is None:
            raise RuntimeError("An ACP session is not open")
        objective = objective.strip()
        if not objective:
            raise ValueError("ACP prompt objective is required")
        if self._prompt_lock.locked():
            raise RuntimeError("An ACP prompt is already active")
        await self._prompt_lock.acquire()
        self._callback.activate(session_id, observer)
        response = None
        try:
            response = await connection.prompt(
                session_id,
                [TextContentBlock(type="text", text=objective)],
            )
            await self._callback.settle_messages()
        finally:
            final_text = self._callback.deactivate()
            self._prompt_lock.release()
        stop_reason = response.stop_reason
        if stop_reason != "cancelled" and not final_text:
            raise RuntimeError("ACP prompt completed without a final response")
        return AcpPromptResult(stop_reason=stop_reason, final_text=final_text)

    async def cancel(self) -> None:
        """Ask the active ACP session to cancel its current prompt."""
        connection = self._connection
        session_id = self._session_id
        if connection is None or session_id is None:
            raise RuntimeError("An ACP session is not open")
        await connection.cancel(session_id)

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
                try:
                    await connection.close_session(session_id)
                except ConnectionError:
                    # The child may close its transport before accepting session/close.
                    pass
        finally:
            await process_context.__aexit__(None, None, None)


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


_OPERATION_METADATA: dict[str, tuple[str, str]] = {
    "read": ("Inspecting files", "Read project files"),
    "search": ("Inspecting files", "Search project files"),
    "edit": ("Editing files", "Edit project files"),
    "delete": ("Editing files", "Delete project files"),
    "move": ("Editing files", "Move project files"),
    "execute": ("Running command", "Run a command"),
    "fetch": ("Fetching information", "Fetch information"),
    "think": ("Organizing work", "Perform the current operation"),
    "switch_mode": ("Updating work mode", "Change the Agent mode"),
}


def _activity_label(kind: str) -> str:
    return _OPERATION_METADATA.get(
        kind, ("Working", "Perform the current operation")
    )[0]


def _permission_operation(kind: str) -> str:
    return _OPERATION_METADATA.get(
        kind, ("Working", "Perform the current operation")
    )[1]


def _permission_name(kind: str) -> str:
    return {
        "allow_once": "Allow once",
        "allow_always": "Always allow",
        "reject_once": "Reject once",
        "reject_always": "Always reject",
    }.get(kind, "Unsupported option")
