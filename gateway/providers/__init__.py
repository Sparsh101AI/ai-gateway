import os

from .anthropic import AnthropicProvider
from .base import Completion, Provider, ProviderError
from .mock import MockProvider
from .openai import OpenAIProvider

_TYPES = {"mock": MockProvider, "openai": OpenAIProvider, "anthropic": AnthropicProvider}


def build_providers(config: dict[str, dict]) -> dict[str, Provider]:
    providers = {}
    for name, cfg in config.items():
        cfg = dict(cfg)
        kind = cfg.pop("type", name)
        key_env = cfg.pop("api_key_env", None)
        if key_env:
            key = os.getenv(key_env)
            if not key:
                continue
            cfg["api_key"] = key
        providers[name] = _TYPES[kind](**cfg)
    return providers


__all__ = ["Completion", "Provider", "ProviderError", "build_providers"]
