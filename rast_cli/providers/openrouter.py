#   openrouter type shit
                

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import requests

from .base import BaseProvider, ChatResponse, ProviderError, ToolCall

OPENROUTER_BASE = "https://openrouter.ai/api/v1"

# Models that reject the temperature parameter.
_NO_TEMPERATURE_MODELS = (
    "openai/o1",
    "openai/o1-mini",
    "openai/o1-preview",
    "openai/o3",
    "openai/o3-mini",
    "openai/o4-mini",
)


def _serialize_tool_args(messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Ensure assistant tool_call arguments are JSON strings (OpenAI format).

    The agent stores arguments as dicts; OpenAI-compatible APIs require them as
    JSON-encoded strings.
    """
    out: List[Dict[str, Any]] = []
    for msg in messages:
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            out.append(msg)
            continue
        new_msg = dict(msg)
        new_calls = []
        for tc in tool_calls:
            tc_copy = dict(tc)
            fn = dict(tc_copy.get("function", {}))
            args = fn.get("arguments", {})
            if not isinstance(args, str):
                fn["arguments"] = json.dumps(args)
            tc_copy["function"] = fn
            new_calls.append(tc_copy)
        new_msg["tool_calls"] = new_calls
        out.append(new_msg)
    return out


class OpenRouterProvider(BaseProvider):
    name = "openrouter"

    def __init__(
        self,
        api_key: Optional[str],
        model: str = "deepseek/deepseek-chat",
        proxy_url: Optional[str] = None,
    ) -> None:
        super().__init__(model)
        self.api_key = api_key
        self.proxy_url = proxy_url
        # Build a persistent session; proxy is set once here.
        self._session = requests.Session()
        if proxy_url:
            self._session.proxies = {
                "http": proxy_url,
                "https": proxy_url,
            }

    def _headers(self) -> Dict[str, str]:
        return {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/rast-cli",
            "X-Title": "Rast-CLI",
        }

    def chat(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.7,
    ) -> ChatResponse:
        if not self.api_key:
            raise ProviderError(
                "OPENROUTER_API_KEY is not set. Export it or add it to your .env, "
                "then switch providers again."
            )

        payload: Dict[str, Any] = {
            "model": self.model,
            "messages": _serialize_tool_args(messages),
            "include_usage": True,
        }
        # Reasoning models (o1/o3 family) reject the temperature parameter.
        if not any(self.model.startswith(m) for m in _NO_TEMPERATURE_MODELS):
            payload["temperature"] = temperature
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        try:
            resp = self._session.post(
                f"{OPENROUTER_BASE}/chat/completions",
                headers=self._headers(),
                json=payload,
                timeout=300,
            )
        except requests.exceptions.ProxyError as exc:
            raise ProviderError(
                f"Proxy connection failed ({self.proxy_url}). "
                "Check /settings proxy or HTTPS_PROXY env var."
            ) from exc
        except requests.exceptions.ConnectionError as exc:
            raise ProviderError("Could not connect to OpenRouter.") from exc
        except requests.exceptions.Timeout as exc:
            raise ProviderError("OpenRouter request timed out.") from exc

        if resp.status_code == 401:
            raise ProviderError(
                "OpenRouter rejected the API key (401 Unauthorized). "
                "Use /key <your-key> to update it."
            )
        if resp.status_code == 403:
            raise ProviderError(
                f"Model '{self.model}' is not available in your region (403). "
                "Try a different model: /use deepseek/deepseek-chat  "
                "or /use google/gemini-2.0-flash-001\n"
                "To use Claude from Hong Kong, set a proxy: "
                "/settings proxy socks5://127.0.0.1:1080"
            )
        if resp.status_code == 402:
            raise ProviderError(
                "OpenRouter: insufficient credits (402). Top up at https://openrouter.ai/credits"
            )
        if resp.status_code == 422:
            try:
                detail = resp.json().get("error", {}).get("message", resp.text[:300])
            except Exception:
                detail = resp.text[:300]
            raise ProviderError(f"OpenRouter rejected the request (422): {detail}")
        if resp.status_code >= 400:
            try:
                detail = resp.json().get("error", {}).get("message", resp.text[:300])
            except Exception:
                detail = resp.text[:300]
            raise ProviderError(
                f"OpenRouter returned HTTP {resp.status_code}: {detail}"
            )

        try:
            data = resp.json()
        except json.JSONDecodeError as exc:
            raise ProviderError("Invalid JSON from OpenRouter.") from exc

        choices = data.get("choices") or []
        if not choices:
            raise ProviderError(f"OpenRouter returned no choices: {data}")
        message = choices[0].get("message", {}) or {}
        content = message.get("content") or ""
        thinking = message.get("reasoning") or ""

        tool_calls: List[ToolCall] = []
        for idx, tc in enumerate(message.get("tool_calls", []) or []):
            fn = tc.get("function", {}) or {}
            args = fn.get("arguments", "{}")
            if isinstance(args, str):
                try:
                    args = json.loads(args or "{}")
                except json.JSONDecodeError:
                    args = {}
            tool_calls.append(
                ToolCall(
                    id=tc.get("id") or f"call_{idx}",
                    name=fn.get("name", ""),
                    arguments=args or {},
                )
            )

        usage = data.get("usage", {}) or {}
        prompt_tokens = int(usage.get("prompt_tokens", 0) or 0)
        completion_tokens = int(usage.get("completion_tokens", 0) or 0)
        total_tokens = int(usage.get("total_tokens", prompt_tokens + completion_tokens) or 0)
        cost = float(usage.get("cost", 0.0) or 0.0)

        return ChatResponse(
            content=content,
            thinking=thinking,
            tool_calls=tool_calls,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost,
            raw_message=message,
        )

    def list_models(self) -> List[str]:
        headers = self._headers() if self.api_key else {}
        try:
            resp = self._session.get(
                f"{OPENROUTER_BASE}/models",
                headers=headers,
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            models = [
                m.get("id", "")
                for m in sorted(
                    data.get("data", []),
                    key=lambda m: m.get("id", ""),
                )
                if m.get("id")
            ]
            return models
        except (requests.RequestException, json.JSONDecodeError):
            return []

    def get_credits(self) -> Optional[Dict[str, Any]]:
        """Return account credit info, or None on failure."""
        if not self.api_key:
            return None
        try:
            resp = self._session.get(
                f"{OPENROUTER_BASE}/credits",
                headers=self._headers(),
                timeout=10,
            )
            resp.raise_for_status()
            return resp.json()
        except (requests.RequestException, json.JSONDecodeError):
            return None
