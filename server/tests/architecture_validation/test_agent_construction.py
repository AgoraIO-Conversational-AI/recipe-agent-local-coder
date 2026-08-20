"""Tests for the selected Managed Voice LLM construction seam."""

from agora_agent.agentkit.vendors import OpenAI

from agent import build_evidence_voice_llm, build_work_voice_llm
from architecture_validation.config import ValidationConfig
from architecture_validation.models import RuntimeSessionBinding
from managed_ingress.models import VoiceMcpLease


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


def test_work_llm_owns_selected_workspace_capability_without_task_categories():
    llm = build_work_voice_llm(
        VoiceMcpLease(
            endpoint="https://example.ngrok.app/mcp/",
            authorization="Bearer secret",
            lease_id="lease-a",
        )
    )

    prompt = llm.system_messages[0]["content"]

    assert "One Project Folder is already selected." in prompt
    assert "Registered tools are capabilities you can use." in prompt
    assert "call start_work with the user's objective in natural language" in prompt
    assert "Do not ask the user for a command" in prompt
    assert "unless the tool reports that it is unavailable" in prompt
    assert "project files, commands, code changes, or verification" not in prompt
