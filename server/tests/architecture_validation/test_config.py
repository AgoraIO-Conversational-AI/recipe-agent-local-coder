"""Tests for fail-closed architecture-validation configuration."""

import pytest

from architecture_validation.config import ValidationConfig


def values(**overrides):
    result = {
        "VOICE_LLM_PATH": "managed",
        "VALIDATION_MODEL": "gpt-4o-mini",
        "PUBLIC_VALIDATION_BASE_URL": "https://example.ngrok.app",
        "MODEL_PROVIDER_BASE_URL": "https://api.openai.com/v1",
        "MODEL_PROVIDER_API_KEY": "",
    }
    result.update(overrides)
    return result


def test_managed_config_uses_corpus_controls_without_provider_key():
    config = ValidationConfig.from_mapping(values())

    assert config.path == "managed"
    assert config.model == "gpt-4o-mini"
    assert config.temperature == 0.0
    assert config.top_p == 1.0
    assert config.max_tokens == 512
    assert config.max_history == 15


def test_custom_config_requires_real_provider_key():
    with pytest.raises(ValueError, match="MODEL_PROVIDER_API_KEY"):
        ValidationConfig.from_mapping(values(VOICE_LLM_PATH="custom"))


@pytest.mark.parametrize("path", ["", "other", "MANAGED"])
def test_path_is_exact(path):
    with pytest.raises(ValueError, match="VOICE_LLM_PATH"):
        ValidationConfig.from_mapping(values(VOICE_LLM_PATH=path))


@pytest.mark.parametrize(
    "url",
    [
        "http://example.ngrok.app",
        "https://example.ngrok.app/path?secret=x",
        "https://example.ngrok.app/path#fragment",
        "not-a-url",
    ],
)
def test_public_url_must_be_clean_https(url):
    with pytest.raises(ValueError, match="PUBLIC_VALIDATION_BASE_URL"):
        ValidationConfig.from_mapping(values(PUBLIC_VALIDATION_BASE_URL=url))


def test_model_must_match_versioned_corpus():
    with pytest.raises(ValueError, match="validation corpus"):
        ValidationConfig.from_mapping(values(VALIDATION_MODEL="different-model"))
