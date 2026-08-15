"""Tests that the two candidates differ only at the LLM provider seam."""

from architecture_validation.config import ValidationConfig
from architecture_validation.models import RuntimeSessionBinding
from agent import build_voice_llm


def config(path):
    return ValidationConfig.from_mapping(
        {
            "VOICE_LLM_PATH": path,
            "VALIDATION_MODEL": "gpt-4o-mini",
            "PUBLIC_VALIDATION_BASE_URL": "https://example.ngrok.app",
            "MODEL_PROVIDER_BASE_URL": "https://api.openai.com/v1",
            "MODEL_PROVIDER_API_KEY": (
                "provider-secret" if path == "custom" else ""
            ),
        }
    )


def test_candidates_share_model_controls_prompt_and_mcp_schema():
    binding = RuntimeSessionBinding.for_test(
        session_id="session-a", scenario_id="scenario-a"
    )

    managed = build_voice_llm(config("managed"), binding)
    custom = build_voice_llm(config("custom"), binding)

    shared_fields = (
        "model",
        "temperature",
        "top_p",
        "max_tokens",
        "max_history",
        "system_messages",
        "mcp_servers",
        "greeting_message",
        "failure_message",
    )
    for field in shared_fields:
        assert getattr(managed, field) == getattr(custom, field)

    mcp = managed.mcp_servers[0]
    assert mcp["allowed_tools"] == [
        "start_work",
        "get_work_status",
        "cancel_work",
        "respond_permission",
    ]
    assert mcp["headers"] == {
        "Authorization": f"Bearer {binding.mcp_bearer}"
    }


def test_only_custom_candidate_points_at_callback_and_uses_callback_bearer():
    binding = RuntimeSessionBinding.for_test(
        session_id="session-a", scenario_id="scenario-a"
    )

    managed = build_voice_llm(config("managed"), binding)
    custom = build_voice_llm(config("custom"), binding)

    assert managed.base_url is None
    assert managed.api_key is None
    assert custom.base_url == "https://example.ngrok.app/llm/chat/completions"
    assert custom.api_key == binding.llm_callback_bearer
