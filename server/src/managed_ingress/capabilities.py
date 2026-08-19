"""Issue, activate, revoke, and rate-limit one Managed MCP capability."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time
import uuid
from collections import defaultdict, deque
from collections.abc import Callable
from dataclasses import dataclass

from .models import CapabilityBinding, CapabilityLease


RATE_LIMITS: dict[str, int] = {
    "start_work": 10,
    "get_work_status": 60,
    "cancel_work": 20,
    "respond_permission": 20,
}
_RATE_BUCKETS: dict[str, str] = {
    "cancel_work": "mutation",
    "respond_permission": "mutation",
}


class CapabilityRegistryError(RuntimeError):
    """A fixed capability lifecycle failure safe for a local caller."""


class CapabilityLimitError(RuntimeError):
    """A fixed public budget failure."""


@dataclass
class _CapabilityRecord:
    lease: CapabilityLease
    bearer_digest: bytes
    binding: CapabilityBinding | None = None
    revoked: bool = False


def _digest(value: str) -> bytes:
    return hashlib.sha256(value.encode("utf-8")).digest()


class CapabilityRegistry:
    """Keep at most one pending or active Work-capable Agent credential."""

    def __init__(
        self,
        *,
        token_factory: Callable[[], str] | None = None,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], float] | None = None,
    ) -> None:
        self._token_factory = token_factory or (lambda: secrets.token_urlsafe(32))
        self._id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self._clock = clock or time.monotonic
        self._record: _CapabilityRecord | None = None

    def prepare(
        self, workspace_id: str, workspace_generation: int
    ) -> CapabilityLease:
        if self._record is not None and not self._record.revoked:
            raise CapabilityRegistryError("voice_agent_already_active")
        if not workspace_id.strip() or workspace_generation < 1:
            raise ValueError("A ready Workspace generation is required")
        bearer = self._token_factory()
        if not bearer:
            raise ValueError("Capability token factory returned an empty value")
        lease = CapabilityLease(
            lease_id=self._id_factory(),
            bearer=bearer,
            workspace_id=workspace_id,
            workspace_generation=workspace_generation,
            issued_at=self._clock(),
        )
        self._record = _CapabilityRecord(lease=lease, bearer_digest=_digest(bearer))
        return lease

    def activate(self, lease_id: str, agora_agent_id: str) -> CapabilityBinding:
        record = self._record
        if record is None or record.revoked or record.lease.lease_id != lease_id:
            raise CapabilityRegistryError("capability_not_found")
        if not agora_agent_id.strip():
            raise ValueError("agora_agent_id is required")
        if record.binding is not None:
            if record.binding.agora_agent_id != agora_agent_id:
                raise CapabilityRegistryError("capability_agent_mismatch")
            return record.binding
        record.binding = CapabilityBinding(
            credential_id=record.lease.lease_id,
            workspace_id=record.lease.workspace_id,
            workspace_generation=record.lease.workspace_generation,
            agora_agent_id=agora_agent_id,
            issued_at=record.lease.issued_at,
        )
        return record.binding

    def resolve(self, bearer: str) -> CapabilityBinding | None:
        record = self._record
        if (
            record is None
            or record.revoked
            or record.binding is None
            or not bearer
        ):
            return None
        if not hmac.compare_digest(record.bearer_digest, _digest(bearer)):
            return None
        return record.binding

    def revoke(self, lease_id: str) -> None:
        record = self._record
        if record is None or record.lease.lease_id != lease_id:
            return
        record.revoked = True
        record.binding = None

    def revoke_active(self) -> None:
        record = self._record
        if record is not None:
            self.revoke(record.lease.lease_id)

    def active_binding(self) -> CapabilityBinding | None:
        record = self._record
        if record is None or record.revoked:
            return None
        return record.binding


class CapabilityRateLimiter:
    """Apply sliding one-minute read/start budgets and one shared mutation budget."""

    def __init__(self, clock: Callable[[], float] | None = None) -> None:
        self._clock = clock or time.monotonic
        self._calls: defaultdict[tuple[str, str], deque[float]] = defaultdict(deque)

    def consume(
        self,
        credential_id: str,
        operation: str,
        *,
        now: float | None = None,
    ) -> None:
        limit = RATE_LIMITS.get(operation)
        if limit is None:
            raise ValueError(f"Unsupported capability operation: {operation}")
        timestamp = self._clock() if now is None else now
        bucket = _RATE_BUCKETS.get(operation, operation)
        calls = self._calls[(credential_id, bucket)]
        cutoff = timestamp - 60.0
        while calls and calls[0] <= cutoff:
            calls.popleft()
        if len(calls) >= limit:
            raise CapabilityLimitError("rate_limited")
        calls.append(timestamp)
