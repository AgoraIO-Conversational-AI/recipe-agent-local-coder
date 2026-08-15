"""Fail-closed configuration shared by both validation candidates."""

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from .models import VoiceLlmPath


CORPUS_PATH = Path(__file__).parents[3] / "validation" / "corpus.json"


@dataclass(frozen=True)
class ValidationConfig:
    path: VoiceLlmPath
    model: str
    temperature: float
    top_p: float
    max_tokens: int
    max_history: int
    public_base_url: str
    provider_base_url: str
    provider_api_key: str

    @classmethod
    def from_env(cls) -> "ValidationConfig":
        return cls.from_mapping(os.environ)

    @classmethod
    def from_mapping(cls, values: Mapping[str, str]) -> "ValidationConfig":
        path = values.get("VOICE_LLM_PATH", "")
        if path not in ("managed", "custom"):
            raise ValueError("VOICE_LLM_PATH must be managed or custom")

        public_base_url = values.get("PUBLIC_VALIDATION_BASE_URL", "").rstrip("/")
        parsed_public = urlparse(public_base_url)
        if (
            parsed_public.scheme != "https"
            or not parsed_public.netloc
            or parsed_public.query
            or parsed_public.fragment
        ):
            raise ValueError("PUBLIC_VALIDATION_BASE_URL must be a clean HTTPS URL")

        corpus = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
        controls = corpus["model_control"]
        model = values.get("VALIDATION_MODEL", "")
        if model != controls["model"]:
            raise ValueError("VALIDATION_MODEL must match the validation corpus")

        provider_base_url = values.get("MODEL_PROVIDER_BASE_URL", "").rstrip("/")
        parsed_provider = urlparse(provider_base_url)
        if parsed_provider.scheme != "https" or not parsed_provider.netloc:
            raise ValueError("MODEL_PROVIDER_BASE_URL must be HTTPS")
        provider_api_key = values.get("MODEL_PROVIDER_API_KEY", "")
        if path == "custom" and not provider_api_key:
            raise ValueError("MODEL_PROVIDER_API_KEY is required for custom")

        return cls(
            path=path,
            model=model,
            temperature=float(controls["temperature"]),
            top_p=float(controls["top_p"]),
            max_tokens=int(controls["max_tokens"]),
            max_history=int(controls["max_history"]),
            public_base_url=public_base_url,
            provider_base_url=provider_base_url,
            provider_api_key=provider_api_key,
        )
