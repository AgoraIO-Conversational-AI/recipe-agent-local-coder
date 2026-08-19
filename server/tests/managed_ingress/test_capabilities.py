"""Per-Agent MCP capability and public rate-budget behavior."""

import pytest

from managed_ingress.capabilities import (
    CapabilityLimitError,
    CapabilityRateLimiter,
    CapabilityRegistry,
    CapabilityRegistryError,
)


def test_pending_lease_is_not_authorized_until_exact_agent_activation():
    registry = CapabilityRegistry(
        token_factory=lambda: "secret-bearer",
        id_factory=lambda: "credential-a",
        clock=lambda: 100.0,
    )

    lease = registry.prepare("scope-a", 3)

    assert registry.resolve("secret-bearer") is None
    assert "secret-bearer" not in repr(lease)
    binding = registry.activate(lease.lease_id, "agora-agent-a")
    assert registry.resolve("secret-bearer") == binding
    assert binding.credential_id == "credential-a"
    assert binding.workspace_id == "scope-a"
    assert binding.workspace_generation == 3
    assert binding.agora_agent_id == "agora-agent-a"

    registry.revoke(lease.lease_id)
    assert registry.resolve("secret-bearer") is None
    assert registry.active_binding() is None


def test_registry_allows_only_one_pending_or_active_voice_agent():
    registry = CapabilityRegistry(
        token_factory=lambda: "secret-bearer",
        id_factory=lambda: "credential-a",
    )
    lease = registry.prepare("scope-a", 1)

    with pytest.raises(CapabilityRegistryError, match="voice_agent_already_active"):
        registry.prepare("scope-a", 1)
    with pytest.raises(CapabilityRegistryError, match="capability_not_found"):
        registry.activate("unknown", "agent-a")

    first = registry.activate(lease.lease_id, "agent-a")
    assert registry.activate(lease.lease_id, "agent-a") == first
    with pytest.raises(CapabilityRegistryError, match="capability_agent_mismatch"):
        registry.activate(lease.lease_id, "agent-b")

    registry.revoke_active()
    replacement = registry.prepare("scope-b", 2)
    assert replacement.workspace_id == "scope-b"


def test_wrong_bearer_never_resolves_and_revocation_is_idempotent():
    registry = CapabilityRegistry(
        token_factory=lambda: "secret-bearer",
        id_factory=lambda: "credential-a",
    )
    lease = registry.prepare("scope-a", 1)
    registry.activate(lease.lease_id, "agent-a")

    assert registry.resolve("wrong-bearer") is None
    registry.revoke(lease.lease_id)
    registry.revoke(lease.lease_id)
    registry.revoke_active()


def test_rate_limiter_uses_separate_sliding_public_budgets():
    limiter = CapabilityRateLimiter()
    for _ in range(10):
        limiter.consume("credential-a", "start_work", now=100.0)
    with pytest.raises(CapabilityLimitError, match="rate_limited"):
        limiter.consume("credential-a", "start_work", now=100.0)

    for _ in range(60):
        limiter.consume("credential-a", "get_work_status", now=100.0)
    with pytest.raises(CapabilityLimitError, match="rate_limited"):
        limiter.consume("credential-a", "get_work_status", now=100.0)

    limiter.consume("credential-b", "start_work", now=100.0)
    limiter.consume("credential-a", "start_work", now=160.001)


def test_rate_limiter_rejects_unknown_operations():
    limiter = CapabilityRateLimiter()

    with pytest.raises(ValueError, match="Unsupported capability operation"):
        limiter.consume("credential-a", "debug", now=100.0)
