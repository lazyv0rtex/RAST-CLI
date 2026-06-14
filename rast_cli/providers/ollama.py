

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import requests

from .base import BaseProvider, ChatResponse, ProviderError, ToolCall


class OllamaProvider(BaseProvider):
    name = "ollama"

    # Models confirmed to not support tool calling — populated at runtime.
    _no_tools_models: set = set()

    def __init__(self, host: str = "http://localhost:11434", model: str = "llama3") -> None:
        super().__init__(model)
        self.host = host.rstrip("/")

    def _post(self, payload: Dict[str, Any]) -> requests.Response:
        url = f"{self.host}/api/chat"
        try:
            return requests.post(url, json=payload, timeout=300)
        except requests.exceptions.ConnectionError as exc:
            raise ProviderError(
                f"Could not connect to Ollama at {self.host}. "
                "Is Ollama running? Start it with `ollama serve`."
            ) from exc
        except requests.exceptions.Timeout as exc:
            raise ProviderError("Ollama request timed out.") from exc

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
    ) -> ChatResponse:
        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": temperature},
        }

        # Skip tools entirely for models we already know don't support them.
        use_tools = tools and self.model not in OllamaProvider._no_tools_models
        if use_tools:
            payload["tools"] = tools

        resp = self._post(payload)

        # Ollama returns 400 when a model doesn't support tool calling.
        # Retry transparently without tools and remember for future calls.
        if resp.status_code == 400 and use_tools:
            err_text = resp.text or ""
            if "does not support tools" in err_text:
                OllamaProvider._no_tools_models.add(self.model)
                payload.pop("tools", None)
                resp = self._post(payload)
                # Emit a one-time warning via the rich console.
                try:
                    from .. import ui as _ui
                    _ui.console.print(
                        f"\n[yellow]Note:[/yellow] [bold]{self.model}[/bold] does not support tool calling. "
                        "Tools are disabled for this model. "
                        "Switch to a tool-capable model (e.g. [cyan]qwen2.5-coder[/cyan], "
                        "[cyan]llama3.1[/cyan]) to re-enable."
                    )
                except Exception:
                    pass

        if resp.status_code == 404:
            raise ProviderError(
                f"Model '{self.model}' not found on Ollama. "
                f"Pull it with `ollama pull {self.model}`."
            )
        if resp.status_code >= 400:
            raise ProviderError(
                f"Ollama returned HTTP {resp.status_code}: {resp.text[:300]}"
            )

        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise ProviderError("Invalid JSON from Ollama.") from exc

        message = data.get("message", {}) or {}
        content = message.get("content", "") or ""
        thinking = message.get("thinking", "") or ""

        tool_calls: List[ToolCall] = []
        for idx, tc in enumerate(message.get("tool_calls", []) or []):
            fn = tc.get("function", {}) or {}
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    args = {}
            tool_calls.append(
                ToolCall(
                    id=tc.get("id") or f"call_{idx}",
                    name=fn.get("name", ""),
                    arguments=args or {},
                )
            )

        prompt_tokens = int(data.get("prompt_eval_count", 0) or 0)
        completion_tokens = int(data.get("eval_count", 0) or 0)

        return ChatResponse(
            content=content,
            thinking=thinking,
            tool_calls=tool_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=prompt_tokens + completion_tokens,
            cost_usd=0.0,
            raw_message=message,
        )

    def list_models(self) -> List[str]:
        try:
            resp = requests.get(f"{self.host}/api/tags", timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return [m.get("name", "") for m in data.get("models", []) if m.get("name")]
        except (requests.RequestException, json.JSONDecodeError):
            return []
