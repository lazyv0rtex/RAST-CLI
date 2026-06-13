"""Tool registry and built-in tools for Rast-CLI."""

from __future__ import annotations

from .registry import Tool, ToolRegistry, ToolResult
from .builtin import build_default_registry


def build_full_registry(config) -> ToolRegistry:
    """Build the registry with built-ins + any enabled integrations."""
    registry = build_default_registry(allow_shell=config.allow_shell)

    if config.github_enabled:
        try:
            from ..integrations.github import register_github_tools
            register_github_tools(registry)
        except ImportError:
            pass

    if config.gmail_enabled:
        try:
            from ..integrations.gmail import register_gmail_tools
            register_gmail_tools(registry)
        except ImportError:
            pass

    return registry


__all__ = ["Tool", "ToolRegistry", "ToolResult", "build_default_registry", "build_full_registry"]
