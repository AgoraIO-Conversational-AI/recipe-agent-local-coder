"""Tests for the separate public and loopback route surfaces."""

from fastapi import FastAPI
from fastapi.testclient import TestClient

from architecture_validation.admin import build_admin_router
from architecture_validation.custom_llm import CustomLlmProxyConfig
from architecture_validation.public_server import create_public_app
from architecture_validation.state import CapabilityRegistry, ValidationStateStore


def test_public_surface_rejects_missing_or_invalid_mcp_bearer():
    store = ValidationStateStore()
    registry = CapabilityRegistry()
    app = create_public_app(store=store, registry=registry, include_custom_llm=False)

    with TestClient(app) as client:
        missing = client.post("/mcp", json={})
        invalid = client.post(
            "/mcp", headers={"Authorization": "Bearer invalid"}, json={}
        )

    assert missing.status_code == 401
    assert invalid.status_code == 401


def test_public_surface_accepts_registered_capability_before_protocol_validation():
    store = ValidationStateStore()
    registry = CapabilityRegistry()
    binding = registry.issue_sync(
        session_id="session-a", scenario_id="scenario-a", ttl_seconds=60
    )
    app = create_public_app(store=store, registry=registry, include_custom_llm=False)

    with TestClient(app) as client:
        response = client.post(
            "/mcp",
            headers={"Authorization": f"Bearer {binding.mcp_bearer}"},
            json={},
        )

    assert response.status_code != 401


def test_public_surface_has_no_loopback_or_lifecycle_routes():
    app = create_public_app(
        store=ValidationStateStore(),
        registry=CapabilityRegistry(),
        include_custom_llm=False,
    )

    with TestClient(app) as client:
        assert client.get("/get_config").status_code == 404
        assert client.post("/startAgent", json={}).status_code == 404
        assert client.post("/stopAgent", json={}).status_code == 404
        assert client.post("/validation/admin/permissions", json={}).status_code == 404
        assert client.get("/validation/results").status_code == 404
        assert client.post("/llm/chat/completions", json={}).status_code == 404


def test_admin_seed_route_rejects_non_loopback_client():
    app = FastAPI()
    app.include_router(
        build_admin_router(store=ValidationStateStore())
    )

    with TestClient(app, client=("203.0.113.10", 50000)) as client:
        response = client.post(
            "/validation/admin/permissions",
            json={
                "session_id": "session-a",
                "question": "Allow tests?",
                "operation": "run_tests",
            },
        )

    assert response.status_code == 403


def test_custom_route_is_mounted_only_when_explicitly_configured():
    store = ValidationStateStore()
    registry = CapabilityRegistry()
    custom_app = create_public_app(
        store=store,
        registry=registry,
        include_custom_llm=True,
        custom_llm_config=CustomLlmProxyConfig(
            provider_base_url="https://provider.example/v1",
            provider_api_key="provider-secret",
            model="gpt-4o-mini",
        ),
    )

    with TestClient(custom_app) as client:
        response = client.post("/llm/chat/completions", json={})

    assert response.status_code == 401
