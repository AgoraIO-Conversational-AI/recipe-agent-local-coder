"""Dedicated ASGI surface containing only authenticated production MCP."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .capabilities import CapabilityRegistry
from .http_policy import IngressHostPolicy, McpIngressMiddleware
from .mcp_app import create_mcp_server
from .tools import ManagedWorkTools


def create_public_app(
    *,
    tools: ManagedWorkTools,
    registry: CapabilityRegistry,
    host_policy: IngressHostPolicy,
    handler_tracker=None,
) -> FastAPI:
    mcp = create_mcp_server(tools)
    mcp_asgi = McpIngressMiddleware(
        mcp.streamable_http_app(),
        registry=registry,
        host_policy=host_policy,
        handler_tracker=handler_tracker,
    )

    @asynccontextmanager
    async def lifespan(_app):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(
        title="Managed MCP Ingress",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.mount("/mcp", mcp_asgi)
    return app
