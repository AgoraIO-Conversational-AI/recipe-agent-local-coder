"""Exactly four production Work tools over stateless Streamable HTTP MCP."""

from typing import Literal, Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .capabilities import CapabilityLimitError, CapabilityRateLimiter
from .http_policy import current_binding, mark_rate_limited
from .tools import ManagedWorkTools


def create_mcp_server(
    tools: ManagedWorkTools, rate_limiter: CapabilityRateLimiter | None = None
) -> FastMCP:
    # Dynamic Host/Origin policy is owned by the outer ASGI middleware because
    # the public ngrok hostname does not exist when FastMCP is constructed.
    mcp = FastMCP(
        "recipe-agent-acp-local",
        instructions="Authenticated local coding Work tools.",
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        max_request_body_size=64 * 1024,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        ),
    )
    limiter = rate_limiter or CapabilityRateLimiter()

    def authorized_binding(operation: str):
        binding = current_binding()
        try:
            limiter.consume(binding.credential_id, operation)
        except CapabilityLimitError:
            mark_rate_limited()
            return None
        return binding

    @mcp.tool()
    async def start_work(objective: str, idempotency_key: str) -> dict[str, object]:
        """Act on the already-selected Project Folder by delegating one complete natural-language objective to the local coding Agent, and return immediately after acceptance."""
        binding = authorized_binding("start_work")
        if binding is None:
            return {"code": "rate_limited", "retriable": True}
        return await tools.start_work(
            binding=binding,
            objective=objective,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    async def get_work_status(work_id: Optional[str] = None) -> dict[str, object]:
        """Read the current or named Work before answering about it."""
        binding = authorized_binding("get_work_status")
        if binding is None:
            return {"code": "rate_limited", "retriable": True}
        return await tools.get_work_status(
            binding=binding, work_id=work_id
        )

    @mcp.tool()
    async def cancel_work(work_id: Optional[str] = None) -> dict[str, object]:
        """Cancel only an explicitly identified current or named Work."""
        binding = authorized_binding("cancel_work")
        if binding is None:
            return {"code": "rate_limited", "retriable": True}
        return await tools.cancel_work(binding=binding, work_id=work_id)

    @mcp.tool()
    async def respond_permission(
        decision: Literal["allow", "reject"],
    ) -> dict[str, object]:
        """Allow or reject only the current pending operation."""
        binding = authorized_binding("respond_permission")
        if binding is None:
            return {"code": "rate_limited", "retriable": True}
        return await tools.respond_permission(
            binding=binding, decision=decision
        )

    return mcp
