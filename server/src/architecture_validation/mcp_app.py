"""Authenticated Streamable HTTP MCP application."""

from contextvars import ContextVar
from typing import Optional

from mcp.server.fastmcp import FastMCP

from .models import PermissionDecision, RuntimeSessionBinding
from .state import CapabilityRegistry, ValidationStateStore
from .tools import ValidationTools


_current_binding: ContextVar[Optional[RuntimeSessionBinding]] = ContextVar(
    "validation_mcp_binding", default=None
)


def current_binding() -> RuntimeSessionBinding:
    binding = _current_binding.get()
    if binding is None:
        raise PermissionError("authenticated session binding is required")
    return binding


class McpBearerAuthMiddleware:
    def __init__(self, app, registry: CapabilityRegistry) -> None:
        self._app = app
        self._registry = registry

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self._app(scope, receive, send)
            return

        headers = {
            key.lower(): value
            for key, value in scope.get("headers", [])
        }
        authorization = headers.get(b"authorization", b"").decode(
            "latin-1", errors="ignore"
        )
        scheme, separator, bearer = authorization.partition(" ")
        binding = (
            self._registry.resolve_mcp_sync(bearer)
            if separator and scheme.lower() == "bearer"
            else None
        )
        if binding is None:
            body = b'{"detail":"invalid or expired MCP capability"}'
            await send(
                {
                    "type": "http.response.start",
                    "status": 401,
                    "headers": [
                        (b"content-type", b"application/json"),
                        (b"content-length", str(len(body)).encode("ascii")),
                        (b"www-authenticate", b"Bearer"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": body})
            return

        token = _current_binding.set(binding)
        try:
            await self._app(scope, receive, send)
        finally:
            _current_binding.reset(token)


def create_mcp_server(store: ValidationStateStore) -> FastMCP:
    tools = ValidationTools(store)
    mcp = FastMCP(
        "recipe-agent-acp-local-validation",
        instructions="Validation-only tools. No ACP or local code execution occurs.",
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        max_request_body_size=64 * 1024,
    )

    @mcp.tool()
    async def start_work(objective: str, idempotency_key: str) -> dict[str, object]:
        """Accept one bounded synthetic Work for architecture validation."""
        return await tools.start_work(
            binding=current_binding(),
            objective=objective,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    async def get_work_status(work_id: Optional[str] = None) -> dict[str, object]:
        """Read the current or named synthetic Work before answering about it."""
        return await tools.get_work_status(
            binding=current_binding(), work_id=work_id
        )

    @mcp.tool()
    async def cancel_work(work_id: Optional[str] = None) -> dict[str, object]:
        """Cancel the current or named synthetic Work."""
        return await tools.cancel_work(binding=current_binding(), work_id=work_id)

    @mcp.tool()
    async def respond_permission(decision: PermissionDecision) -> dict[str, object]:
        """Allow or reject only the currently correlated operation."""
        return await tools.respond_permission(
            binding=current_binding(), decision=decision
        )

    return mcp
