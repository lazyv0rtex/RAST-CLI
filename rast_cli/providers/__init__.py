"""LLM provider clients for Rast-CLI."""

from .base import ChatResponse, ProviderError, BaseProvider
from .ollama import OllamaProvider
from .openrouter import OpenRouterProvider


def build_provider(config) -> BaseProvider:
    """Instantiate the active provider based on the given config."""
    if config.provider == "ollama":
        return OllamaProvider(host=config.ollama_host, model=config.model)
    if config.provider == "openrouter":
        return OpenRouterProvider(
            api_key=config.openrouter_api_key,
            model=config.model,
            proxy_url=config.proxy_url or None,
        )
    raise ProviderError(f"Unknown provider: {config.provider}")


__all__ = [
    "ChatResponse",
    "ProviderError",
    "BaseProvider",
    "OllamaProvider",
    "OpenRouterProvider",
    "build_provider",
]
