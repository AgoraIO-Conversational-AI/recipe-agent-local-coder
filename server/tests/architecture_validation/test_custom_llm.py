"""Tests for the authenticated Custom LLM forwarding adapter."""

import asyncio
import json
from pathlib import Path

import httpx
from fastapi import FastAPI
from fastapi.testclient import TestClient

from architecture_validation.custom_llm import (
    CustomLlmProxyConfig,
    create_custom_llm_router,
    inject_pending_permission,
)
from architecture_validation.state import CapabilityRegistry, ValidationStateStore


FIXTURE = Path(__file__).parent / "fixtures" / "tool_call_stream.txt"


class FixtureStream(httpx.AsyncByteStream):
    def __init__(self, content: bytes):
        self.content = content

    async def __aiter__(self):
        yield self.content


def build_app(handler):
    store = ValidationStateStore()
    registry = CapabilityRegistry()
    binding = registry.issue_sync(
        session_id="session-a", scenario_id="scenario-a", ttl_seconds=60
    )
    transport = httpx.MockTransport(handler)

    def client_factory():
        return httpx.AsyncClient(transport=transport)

    app = FastAPI()
    app.include_router(
        create_custom_llm_router(
            store=store,
            registry=registry,
            config=CustomLlmProxyConfig(
                provider_base_url="https://provider.example/v1",
                provider_api_key="provider-secret",
                model="gpt-4o-mini",
            ),
            client_factory=client_factory,
        )
    )
    return app, store, binding


def request_body():
    return {
        "model": "gpt-4o-mini",
        "messages": [{"role": "user", "content": "Allow it."}],
        "tools": [
            {
                "type": "function",
                "function": {"name": "respond_permission", "parameters": {}},
            }
        ],
        "tool_choice": "auto",
        "temperature": 0.0,
        "top_p": 1.0,
        "max_tokens": 512,
        "stream": True,
        "ignored_extension": "must-not-forward",
    }


def test_missing_or_invalid_callback_bearer_is_rejected_before_provider_call():
    provider_calls = []

    def handler(request):
        provider_calls.append(request)
        return httpx.Response(200, text="data: [DONE]\n\n")

    app, _, _ = build_app(handler)
    with TestClient(app) as client:
        missing = client.post("/llm/chat/completions", json=request_body())
        invalid = client.post(
            "/llm/chat/completions",
            headers={"Authorization": "Bearer invalid"},
            json=request_body(),
        )

    assert missing.status_code == 401
    assert invalid.status_code == 401
    assert provider_calls == []


def test_proxy_injects_current_permission_and_preserves_sse_tool_chunks():
    captured = {}
    fixture = FIXTURE.read_bytes()

    def handler(request):
        captured["headers"] = request.headers
        captured["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=FixtureStream(fixture),
        )

    app, store, binding = build_app(handler)
    asyncio.run(
        store.seed_permission(
            session_id=binding.session_id,
            question="Allow running tests?",
            operation="run_tests",
        )
    )

    with TestClient(app) as client:
        response = client.post(
            "/llm/chat/completions",
            headers={"Authorization": f"Bearer {binding.llm_callback_bearer}"},
            json=request_body(),
        )

    assert response.status_code == 200
    assert response.content == fixture
    assert response.headers["content-type"].startswith("text/event-stream")
    assert captured["headers"]["authorization"] == "Bearer provider-secret"
    assert captured["body"]["model"] == "gpt-4o-mini"
    assert "ignored_extension" not in captured["body"]
    assert captured["body"]["messages"][-1]["role"] == "user"
    assert captured["body"]["messages"][-2]["role"] == "system"
    assert "CURRENT_PENDING_PERMISSION" in captured["body"]["messages"][-2]["content"]


def test_proxy_does_not_inject_another_sessions_permission():
    captured = {}

    def handler(request):
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, stream=FixtureStream(b"data: [DONE]\n\n"))

    app, store, binding = build_app(handler)
    asyncio.run(
        store.seed_permission(
            session_id="session-b",
            question="Allow B?",
            operation="operation_b",
        )
    )

    with TestClient(app) as client:
        response = client.post(
            "/llm/chat/completions",
            headers={"Authorization": f"Bearer {binding.llm_callback_bearer}"},
            json=request_body(),
        )

    assert response.status_code == 200
    assert captured["body"]["messages"] == request_body()["messages"]


def test_injection_replaces_prior_validation_context_instead_of_accumulating():
    messages = [
        {"role": "system", "content": "Base"},
        {"role": "system", "content": "CURRENT_PENDING_PERMISSION\nold"},
        {"role": "user", "content": "Allow it."},
    ]
    from architecture_validation.models import PendingPermission
    from datetime import datetime, timezone

    pending = PendingPermission(
        session_id="session-a",
        authorization_id="new-authorization",
        version=2,
        operation="run_tests",
        question="Allow tests?",
        created_at=datetime.now(timezone.utc),
    )

    injected = inject_pending_permission(messages, pending)

    assert sum(
        message.get("content", "").startswith("CURRENT_PENDING_PERMISSION")
        for message in injected
    ) == 1
    assert "new-authorization" in injected[-2]["content"]


def test_oversized_body_is_rejected_without_provider_call():
    provider_calls = []

    def handler(request):
        provider_calls.append(request)
        return httpx.Response(200, content=b"data: [DONE]\n\n")

    app, _, binding = build_app(handler)
    body = request_body()
    body["messages"][0]["content"] = "x" * 200_000

    with TestClient(app) as client:
        response = client.post(
            "/llm/chat/completions",
            headers={"Authorization": f"Bearer {binding.llm_callback_bearer}"},
            json=body,
        )

    assert response.status_code == 413
    assert provider_calls == []


def test_upstream_error_is_bounded_and_does_not_expose_provider_body():
    def handler(request):
        return httpx.Response(429, content=b"provider-secret internal diagnostic")

    app, _, binding = build_app(handler)
    with TestClient(app) as client:
        response = client.post(
            "/llm/chat/completions",
            headers={"Authorization": f"Bearer {binding.llm_callback_bearer}"},
            json=request_body(),
        )

    assert response.status_code == 502
    assert response.json() == {"detail": "model provider returned HTTP 429"}
    assert "provider-secret" not in response.text
