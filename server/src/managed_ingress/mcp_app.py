"""Exactly four production Work tools over stateless Streamable HTTP MCP."""

from typing import Literal, Optional

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from .http_policy import current_binding
from .tools import ManagedWorkTools


def create_mcp_server(tools: ManagedWorkTools) -> FastMCP:
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

    @mcp.tool()
    async def start_work(objective: str, idempotency_key: str) -> dict[str, object]:
        """Accept one complete executable coding objective without waiting."""
        return await tools.start_work(
            binding=current_binding(),
            objective=objective,
            idempotency_key=idempotency_key,
        )

    @mcp.tool()
    async def get_work_status(work_id: Optional[str] = None) -> dict[str, object]:
        """Read the current or named Work before answering about it."""
        return await tools.get_work_status(
            binding=current_binding(), work_id=work_id
        )

    @mcp.tool()
    async def cancel_work(work_id: Optional[str] = None) -> dict[str, object]:
        """Cancel only an explicitly identified current or named Work."""
        return await tools.cancel_work(binding=current_binding(), work_id=work_id)

    @mcp.tool()
    async def respond_permission(
        decision: Literal["allow", "reject"],
    ) -> dict[str, object]:
        """Allow or reject only the current pending operation."""
        return await tools.respond_permission(
            binding=current_binding(), decision=decision
        )

    return mcp
