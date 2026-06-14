"""The agentic reasoning/tool-execution loop."""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional

from .config import Config
from .providers import BaseProvider, ProviderError, build_provider
from .tools import ToolRegistry, build_full_registry

# Permission callback: (tool_name, preview_text) -> approved (bool)
PermissionCallback = Callable[[str, str], bool]

THINKING_DIRECTIVES = {
    "low": (
        "Be extremely direct and concise. Minimize reasoning text. Prefer taking "
        "actions over explaining. Save tokens."
    ),
    "medium": (
        "Briefly explain your plan before acting, then execute. Keep reasoning "
        "focused and proportional to the task."
    ),
    "high": (
        "Think step by step with explicit, verbose chain-of-thought. Before each "
        "tool call, write out your reasoning, considered alternatives, and why the "
        "chosen action is correct. Be thorough."
    ),
}

MAX_TOOL_ITERATIONS = 25


def build_system_prompt(config: Config) -> str:
    tools_clause = (
        "You have access to file and shell tools. Use them to inspect and modify the "
        "project. Always read files before editing them. Make minimal, correct edits."
        if config.tools_enabled
        else "Tool use is currently DISABLED. Answer using your knowledge only; do not "
        "claim to have modified files."
    )
    return (
        "You are Rast-CLI, an autonomous coding assistant operating inside the user's "
        "terminal within their current project directory. "
        f"{tools_clause} "
        "When you call a tool that modifies files or runs commands, the user must "
        "approve it; if denied, adapt gracefully. After completing the task, give a "
        "short summary of what changed.\n\n"
        f"Reasoning depth ({config.thinking}): {THINKING_DIRECTIVES[config.thinking]}"
    )


class Agent:
    def __init__(
        self,
        config: Config,
        permission_cb: PermissionCallback,
        on_tool_call: Optional[Callable[[str, str], None]] = None,
        on_tool_result: Optional[Callable[[str, bool, str], None]] = None,
        on_assistant_text: Optional[Callable[[str], None]] = None,
        on_thinking: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.config = config
        self.permission_cb = permission_cb
        self.on_tool_call = on_tool_call or (lambda *_: None)
        self.on_tool_result = on_tool_result or (lambda *_: None)
        self.on_assistant_text = on_assistant_text or (lambda *_: None)
        self.on_thinking = on_thinking or (lambda *_: None)

        self.messages: List[Dict[str, Any]] = []
        self.registry: ToolRegistry = build_full_registry(config)
        self.provider: BaseProvider = build_provider(config)

        # Usage tracking.
        self.session_tokens = 0
        self.session_cost = 0.0
        self.last_turn_tokens = 0
        self.last_turn_cost = 0.0

        self._reset_system()

    # ----- lifecycle ---------------------------------------------------
    def _reset_system(self) -> None:
        system = {"role": "system", "content": build_system_prompt(self.config)}
        if self.messages and self.messages[0]["role"] == "system":
            self.messages[0] = system
        else:
            self.messages.insert(0, system)

    def refresh(self) -> None:
        """Rebuild provider/tools/system prompt after a settings change."""
        self.registry = build_full_registry(self.config)
        self.provider = build_provider(self.config)
        self._reset_system()

    def clear(self) -> None:
        self.messages = []
        self._reset_system()

    # ----- main turn ---------------------------------------------------
    def run_turn(self, user_input: str) -> str:
        self.messages.append({"role": "user", "content": user_input})
        self.last_turn_tokens = 0
        self.last_turn_cost = 0.0

        tools = (
            self.registry.to_openai_schemas() if self.config.tools_enabled else None
        )
        final_text = ""

        for _ in range(MAX_TOOL_ITERATIONS):
            response = self.provider.chat(self.messages, tools=tools)
            self._account(response)

            assistant_msg: Dict[str, Any] = {
                "role": "assistant",
                "content": response.content or "",
            }
            if response.tool_calls:
                # Store arguments as a dict (normalized). Each provider
                # serializes to its expected wire format (Ollama wants an
                # object; OpenAI/OpenRouter wants a JSON string).
                assistant_msg["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": "function",
                        "function": {
                            "name": tc.name,
                            "arguments": tc.arguments,
                        },
                    }
                    for tc in response.tool_calls
                ]
            self.messages.append(assistant_msg)

            # Surface explicit reasoning only when thinking depth is high.
            if self.config.thinking == "high" and response.thinking.strip():
                self.on_thinking(response.thinking)

            if response.content and response.content.strip():
                self.on_assistant_text(response.content)

            if not response.tool_calls:
                final_text = response.content or ""
                # Fallback: some reasoning models may leave content empty while
                # putting the answer in the reasoning channel.
                if not final_text.strip() and response.thinking.strip():
                    final_text = response.thinking.strip()
                    self.on_assistant_text(final_text)
                break

            for tc in response.tool_calls:
                result_text = self._execute_tool(tc.name, tc.arguments)
                self.messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "name": tc.name,
                        "content": result_text,
                    }
                )
        else:
            final_text = "[Reached max tool iterations; stopping.]"
            self.messages.append({"role": "assistant", "content": final_text})

        if self.config.autocommit:
            self._autocommit_turn(user_input)

        return final_text

    # ----- helpers -----------------------------------------------------
    def _execute_tool(self, name: str, args: Dict[str, Any]) -> str:
        tool = self.registry.get(name)
        if tool is None:
            return f"Error: unknown tool '{name}'."

        summary = ", ".join(f"{k}={_short(v)}" for k, v in args.items())
        self.on_tool_call(name, summary)

        if tool.requires_permission:
            preview = tool.preview(args) or summary
            approved = self.permission_cb(name, preview)
            if not approved:
                msg = "User denied permission for this action."
                self.on_tool_result(name, False, msg)
                return msg

        try:
            result = tool.run(args)
        except KeyError as exc:
            result_text = f"Error: missing required argument {exc}."
            self.on_tool_result(name, False, result_text)
            return result_text
        except (PermissionError, OSError) as exc:
            result_text = f"Error: {exc}"
            self.on_tool_result(name, False, result_text)
            return result_text
        except Exception as exc:  # noqa: BLE001
            result_text = f"Unexpected tool error: {exc}"
            self.on_tool_result(name, False, result_text)
            return result_text

        self.on_tool_result(name, result.ok, result.output)
        return result.output

    def _autocommit_turn(self, user_input: str) -> None:
        """Stage all changes and commit with the user's prompt as the message."""
        import re
        import subprocess
        from pathlib import Path
        cwd = str(Path.cwd())
        # Only commit if we're inside a git repo.
        check = subprocess.run(
            ["git", "rev-parse", "--is-inside-work-tree"],
            cwd=cwd, capture_output=True, text=True,
        )
        if check.returncode != 0:
            return
        # Check if there is anything to commit.
        status = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=cwd, capture_output=True, text=True,
        )
        if not status.stdout.strip():
            return  # Nothing changed — skip.
        # Build a clean commit message from the user's prompt (max 72 chars).
        summary = user_input.strip().replace("\n", " ")
        if len(summary) > 72:
            summary = summary[:69] + "..."
        commit_msg = f"rast: {summary}"
        subprocess.run(["git", "add", "-A"], cwd=cwd, capture_output=True)
        result = subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=cwd, capture_output=True, text=True,
        )
        if result.returncode == 0:
            sha = ""
            m = re.search(r'\[\S+ ([0-9a-f]+)\]', result.stdout)
            if m:
                sha = f" ({m.group(1)})"
            try:
                from . import ui as _ui
                _ui.console.print(
                    f"[dim]autocommit:[/dim] [green]{commit_msg}[/green]{sha}"
                )
            except Exception:
                pass

    def conversation_turns(self) -> int:
        """Number of user turns in the conversation (excluding system message)."""
        return sum(1 for m in self.messages if m.get("role") == "user")

    def compact(self, summary: str) -> None:
        """Replace conversation history with a single summary assistant message."""
        system = self.messages[0] if self.messages and self.messages[0]["role"] == "system" else None
        self.messages = []
        if system:
            self.messages.append(system)
        self.messages.append({"role": "assistant", "content": f"[Context summary]\n{summary}"})

    def to_json(self) -> str:
        import json as _json
        return _json.dumps(self.messages, indent=2)

    def load_json(self, data: str) -> None:
        import json as _json
        msgs = _json.loads(data)
        if not isinstance(msgs, list):
            raise ValueError("Expected a JSON array of messages.")
        self.messages = msgs
        self._reset_system()

    def _account(self, response) -> None:
        self.last_turn_tokens += response.total_tokens
        self.last_turn_cost += response.cost_usd
        self.session_tokens += response.total_tokens
        self.session_cost += response.cost_usd


def _short(value: Any, limit: int = 60) -> str:
    s = str(value).replace("\n", "\\n")
    return s if len(s) <= limit else s[:limit] + "…"
