"""Outer request policy for the dedicated production MCP listener."""

from __future__ import annotations

import json
from contextvars import ContextVar
from typing import Protocol
from urllib.parse import urlparse

from .capabilities import (
    CapabilityLimitError,
    CapabilityRateLimiter,
    CapabilityRegistry,
    RATE_LIMITS,
)
from .models import CapabilityBinding


MAX_MCP_REQUEST_BYTES = 64 * 1024
_current_binding: ContextVar[CapabilityBinding | None] = ContextVar(
    "managed_mcp_binding", default=None
)


def current_binding() -> CapabilityBinding:
    binding = _current_binding.get()
    if binding is None:
        raise PermissionError("authenticated MCP binding is required")
    return binding


class IngressHostPolicy:
    """Allow loopback plus exactly one currently active public ngrok host."""

    def __init__(self) -> None:
        self._public_host: str | None = None

    def activate(self, public_host: str) -> None:
        normalized = public_host.strip().lower().rstrip(".")
        if not normalized or "/" in normalized or "://" in normalized:
            raise ValueError("A clean public hostname is required")
        self._public_host = normalized

    def deactivate(self) -> None:
        self._public_host = None

    def allows_host(self, value: str) -> bool:
        host = _hostname(value)
        return host in {"127.0.0.1", "localhost", "::1", "testserver"} or (
            self._public_host is not None and host == self._public_host
        )

    def allows_origin(self, value: str) -> bool:
        if not value:
            return True
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower().rstrip(".")
        if host in {"127.0.0.1", "localhost", "::1", "testserver"}:
            return parsed.scheme == "http"
        return (
            self._public_host is not None
            and host == self._public_host
            and parsed.scheme == "https"
        )

    @property
    def public_host(self) -> str | None:
        return self._public_host


def _hostname(value: str) -> str:
    candidate = value.strip().lower().rstrip(".")
    if candidate.startswith("["):
        closing = candidate.find("]")
        return candidate[1:closing] if closing > 0 else candidate
    host, separator, port = candidate.rpartition(":")
    if separator and port.isdigit():
        return host
    return candidate


class HandlerTracker(Protocol):
    def try_enter(self) -> bool: ...

    def leave(self) -> None: ...


class McpIngressMiddleware:
    """Authenticate and bound MCP requests before protocol parsing."""

    def __init__(
        self,
        app,
        *,
        registry: CapabilityRegistry,
        host_policy: IngressHostPolicy,
        handler_tracker: HandlerTracker | None = None,
        rate_limiter: CapabilityRateLimiter | None = None,
    ) -> None:
        self._app = app
        self._registry = registry
        self._host_policy = host_policy
        self._handler_tracker = handler_tracker
        self._rate_limiter = rate_limiter

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return
        method = str(scope.get("method", "")).upper()
        if method not in {"GET", "POST", "DELETE"}:
            await _respond(send, 405, "method_not_allowed")
            return
        headers = {key.lower(): value for key, value in scope.get("headers", [])}
        authorization = headers.get(b"authorization", b"").decode(
            "latin-1", errors="ignore"
        )
        scheme, separator, bearer = authorization.partition(" ")
        binding = (
            self._registry.resolve(bearer)
            if separator and scheme.casefold() == "bearer"
            else None
        )
        if binding is None:
            await _respond(send, 401, "invalid_or_expired_capability", bearer=True)
            return
        host = headers.get(b"host", b"").decode("latin-1", errors="ignore")
        if not self._host_policy.allows_host(host):
            await _respond(send, 421, "invalid_host")
            return
        origin = headers.get(b"origin", b"").decode("latin-1", errors="ignore")
        if not self._host_policy.allows_origin(origin):
            await _respond(send, 403, "invalid_origin")
            return
        entered = self._handler_tracker is None or self._handler_tracker.try_enter()
        if not entered:
            await _respond(send, 503, "runtime_unavailable")
            return
        try:
            replay_receive = receive
            if method == "POST":
                content_type = headers.get(b"content-type", b"").decode(
                    "latin-1", errors="ignore"
                )
                if content_type.split(";", 1)[0].strip().casefold() != "application/json":
                    await _respond(send, 415, "unsupported_content_type")
                    return
                content_length = headers.get(b"content-length", b"").decode(
                    "ascii", errors="ignore"
                )
                if content_length.isdigit() and int(content_length) > MAX_MCP_REQUEST_BYTES:
                    await _respond(send, 413, "request_too_large")
                    return
                body = bytearray()
                more_body = True
                while more_body:
                    message = await receive()
                    if message.get("type") != "http.request":
                        continue
                    body.extend(message.get("body", b""))
                    if len(body) > MAX_MCP_REQUEST_BYTES:
                        await _respond(send, 413, "request_too_large")
                        return
                    more_body = bool(message.get("more_body", False))
                if self._rate_limiter is not None:
                    try:
                        operations = _tool_operations(bytes(body))
                        for operation in operations:
                            self._rate_limiter.consume(
                                binding.credential_id, operation
                            )
                    except CapabilityLimitError:
                        await _respond(send, 429, "rate_limited")
                        return
                delivered = False

                async def replay_receive():
                    nonlocal delivered
                    if not delivered:
                        delivered = True
                        return {
                            "type": "http.request",
                            "body": bytes(body),
                            "more_body": False,
                        }
                    return {"type": "http.disconnect"}

            token = _current_binding.set(binding)
            try:
                await self._app(scope, replay_receive, send)
            finally:
                _current_binding.reset(token)
        finally:
            if self._handler_tracker is not None:
                self._handler_tracker.leave()


async def _respond(send, status: int, code: str, *, bearer: bool = False) -> None:
    body = json.dumps({"code": code}, separators=(",", ":")).encode("utf-8")
    headers = [
        (b"content-type", b"application/json"),
        (b"content-length", str(len(body)).encode("ascii")),
    ]
    if bearer:
        headers.append((b"www-authenticate", b"Bearer"))
    await send({"type": "http.response.start", "status": status, "headers": headers})
    await send({"type": "http.response.body", "body": body})


def _tool_operations(body: bytes) -> tuple[str, ...]:
    try:
        payload = json.loads(body)
    except (json.JSONDecodeError, UnicodeDecodeError):
        return ()
    messages = payload if isinstance(payload, list) else [payload]
    operations = []
    for message in messages:
        if not isinstance(message, dict) or message.get("method") != "tools/call":
            continue
        params = message.get("params")
        name = params.get("name") if isinstance(params, dict) else None
        if isinstance(name, str) and name in RATE_LIMITS:
            operations.append(name)
    return tuple(operations)
