"""Public validation ingress containing only authenticated callback routes."""

from contextlib import asynccontextmanager

from fastapi import FastAPI

from .custom_llm import CustomLlmProxyConfig, create_custom_llm_router
from .config import ValidationConfig
from .mcp_app import McpBearerAuthMiddleware, create_mcp_server
from .runtime import capability_registry, state_store
from .state import CapabilityRegistry, ValidationStateStore


def create_public_app(
    *,
    store: ValidationStateStore,
    registry: CapabilityRegistry,
    include_custom_llm: bool,
    custom_llm_config: CustomLlmProxyConfig | None = None,
) -> FastAPI:
    mcp = create_mcp_server(store)
    mcp_asgi = McpBearerAuthMiddleware(mcp.streamable_http_app(), registry)

    @asynccontextmanager
    async def lifespan(_app):
        async with mcp.session_manager.run():
            yield

    app = FastAPI(
        title="Voice LLM Validation Public Ingress",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.include_custom_llm = include_custom_llm
    if include_custom_llm:
        if custom_llm_config is None:
            raise ValueError("custom_llm_config is required for the Custom path")
        app.include_router(
            create_custom_llm_router(
                store=store,
                registry=registry,
                config=custom_llm_config,
            )
        )
    app.mount("/mcp", mcp_asgi)
    return app


def create_public_app_for_config(config: ValidationConfig) -> FastAPI:
    custom_config = None
    if config.path == "custom":
        custom_config = CustomLlmProxyConfig(
            provider_base_url=config.provider_base_url,
            provider_api_key=config.provider_api_key,
            model=config.model,
        )
    return create_public_app(
        store=state_store,
        registry=capability_registry,
        include_custom_llm=config.path == "custom",
        custom_llm_config=custom_config,
    )


app = create_public_app(
    store=state_store,
    registry=capability_registry,
    include_custom_llm=False,
)
