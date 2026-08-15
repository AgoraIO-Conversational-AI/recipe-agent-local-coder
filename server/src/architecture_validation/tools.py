"""Shared MCP tool behavior for both Voice LLM candidates."""

from datetime import datetime, timezone
from typing import Optional

from .models import PermissionDecision, RuntimeSessionBinding, ToolObservation
from .state import ValidationStateStore


class ValidationTools:
    def __init__(self, store: ValidationStateStore) -> None:
        self._store = store

    async def _observe(
        self, binding: RuntimeSessionBinding, name: str, arguments: dict[str, object]
    ) -> None:
        bounded = {
            key: value[:512] if isinstance(value, str) else value
            for key, value in arguments.items()
        }
        await self._store.record_observation(
            ToolObservation(
                scenario_id=binding.scenario_id,
                session_id=binding.session_id,
                name=name,
                arguments=bounded,
                observed_at=datetime.now(timezone.utc),
            )
        )

    async def start_work(
        self,
        *,
        binding: RuntimeSessionBinding,
        objective: str,
        idempotency_key: str,
    ) -> dict[str, object]:
        objective = objective.strip()
        idempotency_key = idempotency_key.strip()
        if not objective:
            raise ValueError("objective is required")
        if not idempotency_key:
            raise ValueError("idempotency_key is required")
        await self._observe(
            binding,
            "start_work",
            {"objective": objective, "idempotency_key": idempotency_key},
        )
        code, work = await self._store.accept_work(
            session_id=binding.session_id,
            objective=objective,
            idempotency_key=idempotency_key,
        )
        if work is None:
            return {"code": code}
        return {"code": code, "work_id": work.work_id, "state": work.state}

    async def get_work_status(
        self, *, binding: RuntimeSessionBinding, work_id: Optional[str] = None
    ) -> dict[str, object]:
        await self._observe(binding, "get_work_status", {"work_id": work_id})
        work = await self._store.find_work(
            session_id=binding.session_id, work_id=work_id
        )
        if work is None:
            return {"code": "work_not_found"}
        return {
            "code": "work_found",
            "work_id": work.work_id,
            "state": work.state,
            "objective": work.objective,
        }

    async def cancel_work(
        self, *, binding: RuntimeSessionBinding, work_id: Optional[str] = None
    ) -> dict[str, object]:
        await self._observe(binding, "cancel_work", {"work_id": work_id})
        work = await self._store.cancel_work(
            session_id=binding.session_id, work_id=work_id
        )
        if work is None:
            return {"code": "work_not_found"}
        return {
            "code": "work_cancelled",
            "work_id": work.work_id,
            "state": work.state,
        }

    async def respond_permission(
        self, *, binding: RuntimeSessionBinding, decision: PermissionDecision
    ) -> dict[str, object]:
        if decision not in ("allow", "reject"):
            raise ValueError("decision must be allow or reject")
        await self._observe(
            binding, "respond_permission", {"decision": decision}
        )
        pending = await self._store.current_permission(binding.session_id)
        if pending is None:
            return {"code": "permission_not_found"}
        result = await self._store.resolve_permission(
            session_id=binding.session_id,
            authorization_id=pending.authorization_id,
            version=pending.version,
            decision=decision,
        )
        response: dict[str, object] = {"code": result.code}
        if result.authorization_id is not None:
            response["authorization_id"] = result.authorization_id
        if result.version is not None:
            response["version"] = result.version
        if result.decision is not None:
            response["decision"] = result.decision
        return response
