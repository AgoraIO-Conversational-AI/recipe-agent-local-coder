"""Tests for the selected Managed Voice LLM construction seam."""

from agora_agent.agentkit.vendors import OpenAI

from agent import build_evidence_voice_llm
from architecture_validation.config import ValidationConfig
from architecture_validation.models import RuntimeSessionBinding


def config() -> ValidationConfig:
    return ValidationConfig.from_mapping(
        {
            "VALIDATION_MODEL": "gpt-4o-mini",
            "PUBLIC_VALIDATION_BASE_URL": "https://example.ngrok.app",
        }
    )


def test_selected_baseline_builds_managed_llm_with_shared_mcp_tools():
    binding = RuntimeSessionBinding.for_test(
        session_id="session-a", scenario_id="scenario-a"
    )

    llm = build_evidence_voice_llm(config(), binding)

    assert isinstance(llm, OpenAI)
    assert llm.model == "gpt-4o-mini"
    assert llm.base_url is None
    assert llm.api_key is None
    assert llm.mcp_servers[0]["allowed_tools"] == [
        "start_work",
        "get_work_status",
        "cancel_work",
        "respond_permission",
    ]
    assert llm.mcp_servers[0]["headers"] == {
        "Authorization": f"Bearer {binding.mcp_bearer}"
    }
