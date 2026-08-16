"""Public evidence ingress containing only authenticated MCP routes."""

from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI

from .config import ValidationConfig
from .mcp_app import McpBearerAuthMiddleware, create_mcp_server
from .runtime import capability_registry, state_store
from .state import CapabilityRegistry, ValidationStateStore


def create_public_app(
    *,
    store: ValidationStateStore,
    registry: CapabilityRegistry,
    public_host: str | None = None,
) -> FastAPI:
    mcp = create_mcp_server(store, public_host=public_host)
    mcp_asgi = McpBearerAuthMiddleware(mcp.streamable_http_app(), registry)

    @asynccontextmanager
    async def lifespan(_app):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(
        title="Managed Voice LLM Evidence Ingress",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.mount("/mcp", mcp_asgi)
    return app


def create_public_app_for_config(config: ValidationConfig) -> FastAPI:
    return create_public_app(
        store=state_store,
        registry=capability_registry,
        public_host=urlparse(config.public_base_url).hostname,
    )


app = create_public_app(
    store=state_store,
    registry=capability_registry,
)
