"""Thin authenticated OpenAI-compatible forwarding adapter."""

import json
from dataclasses import dataclass
from typing import Callable, Optional, Sequence

import httpx
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse

from .context import project_pending_permission
from .models import PendingPermission
from .state import CapabilityRegistry, ValidationStateStore


MAX_REQUEST_BODY_BYTES = 128 * 1024
_FORWARDED_FIELDS = {
    "messages",
    "tools",
    "tool_choice",
    "temperature",
    "top_p",
    "max_tokens",
    "stream",
}


@dataclass(frozen=True)
class CustomLlmProxyConfig:
    provider_base_url: str
    provider_api_key: str
    model: str


def inject_pending_permission(
    messages: Sequence[dict[str, object]],
    pending: Optional[PendingPermission],
) -> list[dict[str, object]]:
    """Replace prior validation context and inject current state before user."""
    cleaned = [
        dict(message)
        for message in messages
        if not (
            message.get("role") == "system"
            and isinstance(message.get("content"), str)
            and message["content"].startswith("CURRENT_PENDING_PERMISSION\n")
        )
    ]
    dynamic = project_pending_permission(pending)
    if dynamic is None:
        return cleaned

    user_index = next(
        (
            index
            for index in range(len(cleaned) - 1, -1, -1)
            if cleaned[index].get("role") == "user"
        ),
        len(cleaned),
    )
    cleaned.insert(user_index, dynamic)
    return cleaned


def _bearer(authorization: Optional[str]) -> Optional[str]:
    if not authorization:
        return None
    scheme, separator, token = authorization.partition(" ")
    if not separator or scheme.lower() != "bearer" or not token:
        return None
    return token


def _default_client_factory() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5.0, read=60.0, write=10.0, pool=5.0)
    )


def create_custom_llm_router(
    *,
    store: ValidationStateStore,
    registry: CapabilityRegistry,
    config: CustomLlmProxyConfig,
    client_factory: Callable[[], httpx.AsyncClient] = _default_client_factory,
) -> APIRouter:
    router = APIRouter()
    provider_url = (
        config.provider_base_url.rstrip("/") + "/chat/completions"
    )

    @router.post("/llm/chat/completions")
    async def chat_completions(request: Request):
        binding = registry.resolve_llm_sync(
            _bearer(request.headers.get("authorization")) or ""
        )
        if binding is None:
            return JSONResponse(
                status_code=401,
                content={"detail": "invalid or expired LLM callback capability"},
                headers={"WWW-Authenticate": "Bearer"},
            )

        content_length = request.headers.get("content-length")
        try:
            declared_length = int(content_length) if content_length else 0
        except ValueError:
            return JSONResponse(
                status_code=400, content={"detail": "invalid content length"}
            )
        if declared_length > MAX_REQUEST_BODY_BYTES:
            return JSONResponse(
                status_code=413, content={"detail": "request body too large"}
            )
        raw_body = await request.body()
        if len(raw_body) > MAX_REQUEST_BODY_BYTES:
            return JSONResponse(
                status_code=413, content={"detail": "request body too large"}
            )

        try:
            incoming = json.loads(raw_body)
        except (json.JSONDecodeError, UnicodeDecodeError):
            return JSONResponse(
                status_code=400, content={"detail": "invalid JSON body"}
            )
        messages = incoming.get("messages")
        if not isinstance(messages, list) or not all(
            isinstance(message, dict) for message in messages
        ):
            return JSONResponse(
                status_code=400, content={"detail": "messages must be an array"}
            )
        if incoming.get("stream") is not True:
            return JSONResponse(
                status_code=400, content={"detail": "stream must be true"}
            )

        pending = await store.current_permission(binding.session_id)
        outgoing = {
            key: incoming[key]
            for key in _FORWARDED_FIELDS
            if key in incoming
        }
        outgoing["model"] = config.model
        outgoing["messages"] = inject_pending_permission(messages, pending)

        client = client_factory()
        upstream_request = client.build_request(
            "POST",
            provider_url,
            headers={
                "Authorization": f"Bearer {config.provider_api_key}",
                "Content-Type": "application/json",
                "Accept": "text/event-stream",
            },
            json=outgoing,
        )
        try:
            upstream = await client.send(upstream_request, stream=True)
        except httpx.RequestError:
            await client.aclose()
            return JSONResponse(
                status_code=502, content={"detail": "model provider unavailable"}
            )

        if upstream.status_code < 200 or upstream.status_code >= 300:
            status_code = upstream.status_code
            await upstream.aclose()
            await client.aclose()
            return JSONResponse(
                status_code=502,
                content={
                    "detail": f"model provider returned HTTP {status_code}"
                },
            )

        async def stream_provider():
            try:
                async for chunk in upstream.aiter_raw():
                    yield chunk
            finally:
                await upstream.aclose()
                await client.aclose()

        return StreamingResponse(
            stream_provider(), media_type="text/event-stream"
        )

    return router
