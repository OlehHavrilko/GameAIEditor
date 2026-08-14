from __future__ import annotations

import os
from typing import Any

from .base import VisionProvider
from .ollama import OllamaVisionProvider
from .openai_compatible import OpenAICompatibleVisionProvider


def _get(config: Any, name: str, default: Any = None) -> Any:
    if isinstance(config, dict):
        return config.get(name, default)
    return getattr(config, name, default)


def create_vision_provider(config: Any) -> VisionProvider:
    provider = str(_get(config, "provider", "ollama")).casefold()
    base_url = str(_get(config, "base_url", ""))
    model = str(_get(config, "model", ""))
    timeout = float(_get(config, "request_timeout_seconds", None) or _get(config, "timeout", 120.0))
    api_key = _get(config, "api_key")
    if isinstance(api_key, str) and api_key.startswith("${env:") and api_key.endswith("}"):
        api_key = os.getenv(api_key[6:-1])
    if provider == "ollama":
        return OllamaVisionProvider(base_url=base_url, model=model, timeout_seconds=timeout)
    if provider in {"lm_studio", "lmstudio", "openrouter", "openai", "openai-compatible", "custom"}:
        return OpenAICompatibleVisionProvider(
            base_url=base_url,
            model=model,
            api_key=api_key,
            timeout_seconds=timeout,
            provider_name=provider,
        )
    raise ValueError(f"Unsupported Vision provider: {provider}")