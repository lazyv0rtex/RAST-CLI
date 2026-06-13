"""Shared provider interfaces and data structures."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


class ProviderError(Exception):
    """Raised when a provider request fails in a recoverable way."""


@dataclass
class ToolCall:
    """A single tool/function invocation requested by the model."""

    id: str
    name: str
    arguments: Dict[str, Any]


@dataclass
class ChatResponse:
    """Normalized response across providers."""

    content: str = ""
    thinking: str = ""
    tool_calls: List[ToolCall] = field(default_factory=list)
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    # Provider-reported cost in USD, when available (OpenRouter).
    cost_usd: float = 0.0
    raw_message: Dict[str, Any] = field(default_factory=dict)


class BaseProvider:
    """Abstract base class for chat providers."""

    name: str = "base"

    def __init__(self, model: str) -> None:
        self.model = model

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
    ) -> ChatResponse:
        raise NotImplementedError

    def list_models(self) -> List[str]:
        """Return available model names, if discoverable."""
        return []

    def get_credits(self) -> Optional[Dict[str, Any]]:
        """Return credit/balance info for the provider account, if available."""
        return None
