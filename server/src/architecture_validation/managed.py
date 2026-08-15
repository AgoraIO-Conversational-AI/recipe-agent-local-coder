"""Managed Voice LLM dynamic-context adapter using the official Agent session."""

import asyncio
from typing import Optional, Protocol, Sequence

from .context import project_pending_permission, project_permission_speech
from .models import PendingPermission
from .state import ValidationStateStore


class ManagedAgentSession(Protocol):
    async def update(self, properties: object) -> None: ...

    async def say(
        self,
        text: str,
        priority: Optional[str] = None,
        interruptable: Optional[bool] = None,
    ) -> None: ...


class ManagedContextSynchronizer:
    """Replace live system messages from authoritative validation state."""

    def __init__(
        self,
        store: ValidationStateStore,
        base_messages: Sequence[dict[str, str]],
    ) -> None:
        self._store = store
        self._base_messages = [dict(message) for message in base_messages]
        self._applied_versions: dict[str, Optional[int]] = {}
        self._lock = asyncio.Lock()

    def applied_version(self, session_id: str) -> Optional[int]:
        return self._applied_versions.get(session_id)

    async def on_permission_changed(
        self, *, session_id: str, session: ManagedAgentSession
    ) -> Optional[int]:
        async with self._lock:
            pending = await self._store.current_permission(session_id)
            target_version = pending.version if pending else None
            if (
                session_id in self._applied_versions
                and self._applied_versions[session_id] == target_version
            ):
                return target_version

            system_messages = [dict(message) for message in self._base_messages]
            dynamic_message = project_pending_permission(pending)
            if dynamic_message is not None:
                system_messages.append(dynamic_message)

            await session.update(
                {"llm": {"system_messages": system_messages}}
            )
            self._applied_versions[session_id] = target_version
            return target_version

    async def announce_permission(
        self, *, session: ManagedAgentSession, pending: PendingPermission
    ) -> None:
        await session.say(
            project_permission_speech(pending),
            priority="APPEND",
            interruptable=True,
        )
