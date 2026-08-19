"""Route isolation and request policy for the production MCP listener."""

import json

import pytest
from fastapi.testclient import TestClient

from managed_ingress.capabilities import CapabilityRateLimiter, CapabilityRegistry
from managed_ingress.http_policy import IngressHostPolicy, McpIngressMiddleware
from managed_ingress.mcp_app import create_mcp_server
from managed_ingress.public_server import create_public_app


class FakeTools:
    async def start_work(self, **kwargs):
        return {"code": "work_accepted", "arguments": sorted(kwargs)}

    async def get_work_status(self, **kwargs):
        return {"code": "work_found", "arguments": sorted(kwargs)}

    async def cancel_work(self, **kwargs):
        return {"code": "work_cancelled", "arguments": sorted(kwargs)}

    async def respond_permission(self, **kwargs):
        return {"code": "permission_resolved", "arguments": sorted(kwargs)}


def active_registry() -> tuple[CapabilityRegistry, str]:
    registry = CapabilityRegistry(
        token_factory=lambda: "test-bearer",
        id_factory=lambda: "credential-a",
    )
    lease = registry.prepare("scope-a", 1)
    registry.activate(lease.lease_id, "agent-a")
    return registry, lease.bearer


@pytest.mark.anyio
async def test_server_registers_exactly_four_public_tools():
    mcp = create_mcp_server(FakeTools())

    tools = await mcp.list_tools()

    assert [tool.name for tool in tools] == [
        "start_work",
        "get_work_status",
        "cancel_work",
        "respond_permission",
    ]


def test_public_app_exposes_only_authenticated_mcp():
    registry, bearer = active_registry()
    host_policy = IngressHostPolicy()
    app = create_public_app(
        tools=FakeTools(), registry=registry, host_policy=host_policy
    )

    with TestClient(app) as client:
        for method, route in [
            ("GET", "/get_config"),
            ("POST", "/startAgent"),
            ("GET", "/local/workspace"),
            ("GET", "/events"),
            ("GET", "/docs"),
        ]:
            assert client.request(method, route).status_code == 404

        assert client.post("/mcp/", json={}).status_code == 401
        assert (
            client.post(
                "/mcp/",
                headers={"Authorization": "Bearer invalid"},
                json={},
            ).status_code
            == 401
        )
        authenticated = client.post(
            "/mcp/",
            headers={"Authorization": f"Bearer {bearer}"},
            json={},
        )
        assert authenticated.status_code not in {401, 403, 404, 413, 415, 421}


def test_dynamic_host_origin_content_type_and_body_limits_fail_closed():
    registry, bearer = active_registry()
    host_policy = IngressHostPolicy()
    host_policy.activate("voice.example.test")
    app = create_public_app(
        tools=FakeTools(), registry=registry, host_policy=host_policy
    )
    auth = {"Authorization": f"Bearer {bearer}"}

    with TestClient(app) as client:
        allowed = client.post(
            "/mcp/",
            headers={
                **auth,
                "Host": "voice.example.test",
                "Origin": "https://voice.example.test",
            },
            json={},
        )
        wrong_host = client.post(
            "/mcp/", headers={**auth, "Host": "attacker.example"}, json={}
        )
        wrong_origin = client.post(
            "/mcp/",
            headers={
                **auth,
                "Host": "voice.example.test",
                "Origin": "https://attacker.example",
            },
            json={},
        )
        wrong_type = client.post(
            "/mcp/", headers={**auth, "Content-Type": "text/plain"}, content="x"
        )
        too_large = client.post(
            "/mcp/",
            headers={**auth, "Content-Type": "application/json"},
            content=json.dumps({"value": "x" * (64 * 1024)}),
        )

    assert allowed.status_code != 421
    assert wrong_host.status_code == 421
    assert wrong_origin.status_code == 403
    assert wrong_type.status_code == 415
    assert too_large.status_code == 413


def test_tool_rate_exhaustion_returns_http_429():
    registry, bearer = active_registry()
    app = create_public_app(
        tools=FakeTools(),
        registry=registry,
        host_policy=IngressHostPolicy(),
        rate_limiter=CapabilityRateLimiter(clock=lambda: 100.0),
    )
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "start_work",
            "arguments": {"objective": "test", "idempotency_key": "turn-a"},
        },
    }

    with TestClient(app) as client:
        responses = [
            client.post(
                "/mcp/",
                headers={"Authorization": f"Bearer {bearer}"},
                json=request,
            )
            for _ in range(11)
        ]

    assert responses[-1].status_code == 429
    assert responses[-1].json() == {"code": "rate_limited"}


@pytest.mark.anyio
async def test_invalid_bearer_is_rejected_without_reading_body():
    registry = CapabilityRegistry()
    body_read = False
    messages = []

    async def downstream(scope, receive, send):
        del scope, receive, send
        raise AssertionError("invalid credentials must not reach MCP")

    middleware = McpIngressMiddleware(
        downstream,
        registry=registry,
        host_policy=IngressHostPolicy(),
    )

    async def receive():
        nonlocal body_read
        body_read = True
        return {"type": "http.request", "body": b"secret", "more_body": False}

    async def send(message):
        messages.append(message)

    await middleware(
        {
            "type": "http",
            "method": "POST",
            "path": "/",
            "headers": [
                (b"host", b"localhost"),
                (b"content-type", b"application/json"),
            ],
        },
        receive,
        send,
    )

    assert body_read is False
    assert messages[0]["status"] == 401
