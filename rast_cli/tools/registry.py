"""Tool registry primitives."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional


@dataclass
class ToolResult:
    """Outcome of a tool execution."""

    ok: bool
    output: str
    # Optional preview to show the user before/after execution.
    preview: Optional[str] = None


# A handler receives the parsed arguments dict and returns a ToolResult.
ToolHandler = Callable[[Dict[str, Any]], ToolResult]
# A previewer produces a human-readable description of what will happen,
# used for the permission prompt. Returns None if nothing to preview.
ToolPreviewer = Callable[[Dict[str, Any]], Optional[str]]


@dataclass
class Tool:
    name: str
    description: str
    parameters: Dict[str, Any]  # JSON Schema for the function arguments
    handler: ToolHandler
    # Whether this tool mutates the filesystem / runs commands and therefore
    # requires explicit user confirmation before running.
    requires_permission: bool = False
    previewer: Optional[ToolPreviewer] = None

    def to_openai_schema(self) -> Dict[str, Any]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.parameters,
            },
        }

    def preview(self, args: Dict[str, Any]) -> Optional[str]:
        if self.previewer is None:
            return None
        try:
            return self.previewer(args)
        except Exception:  # noqa: BLE001 - preview must never crash the loop
            return None

    def run(self, args: Dict[str, Any]) -> ToolResult:
        return self.handler(args)


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: Dict[str, Tool] = {}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def get(self, name: str) -> Optional[Tool]:
        return self._tools.get(name)

    def names(self) -> List[str]:
        return sorted(self._tools)

    def all(self) -> List[Tool]:
        return [self._tools[n] for n in self.names()]

    def to_openai_schemas(self) -> List[Dict[str, Any]]:
        return [t.to_openai_schema() for t in self.all()]
