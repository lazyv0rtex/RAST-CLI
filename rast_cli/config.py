"""Configuration management for Rast-CLI.

Settings are persisted to ``~/.config/rast-cli/config.json`` and may be
overridden by environment variables (optionally loaded from a local ``.env``).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

CONFIG_DIR = Path(os.path.expanduser("~")) / ".config" / "rast-cli"
CONFIG_PATH = CONFIG_DIR / "config.json"

VALID_PROVIDERS = ("ollama", "openrouter")
VALID_THINKING = ("low", "medium", "high")

DEFAULT_MODELS = {
    "ollama": "llama3",
    "openrouter": "deepseek/deepseek-chat",
}

PRESET_MODELS = {
    "ollama": [
        "llama3",
        "llama3.1",
        "llama3.2",
        "mistral",
        "mixtral",
        "qwen2.5-coder",
        "qwen2.5-coder:7b",
        "qwen2.5-coder:14b",
        "qwen2.5-coder:32b",
        "qwen3.5:latest",
        "deepseek-coder",
        "deepseek-coder-v2",
        "deepseek-r1",
        "deepseek-r1:7b",
        "deepseek-r1:14b",
        "codellama",
        "codellama:13b",
        "codellama:34b",
        "phi3",
        "phi3.5",
        "gemma2",
        "gemma2:27b",
        "starcoder2",
        "nomic-embed-text",
    ],
    "openrouter": [
        "deepseek/deepseek-chat",
        "deepseek/deepseek-r1",
        "anthropic/claude-sonnet-4-5",
        "anthropic/claude-sonnet-4",
        "anthropic/claude-haiku-4-5",
        "anthropic/claude-3-5-sonnet",
        "anthropic/claude-3-5-haiku",
        "anthropic/claude-3-opus",
        "openai/gpt-4o",
        "openai/gpt-4o-mini",
        "openai/o1",
        "openai/o3-mini",
        "openai/o4-mini",
        "google/gemini-2.5-flash-preview",
        "google/gemini-2.5-pro-preview",
        "google/gemini-2.0-flash-001",
        "meta-llama/llama-3.3-70b-instruct",
        "meta-llama/llama-3.1-8b-instruct",
        "qwen/qwen3-235b-a22b",
        "qwen/qwen3-32b",
        "mistralai/mistral-large",
        "mistralai/codestral-latest",
        "microsoft/phi-4",
        "x-ai/grok-3-mini-beta",
        "x-ai/grok-3-beta",
    ],
}


def _load_dotenv() -> None:
    """Minimal .env loader (no external dependency).

    Looks for a ``.env`` file in the current working directory and loads any
    keys that are not already present in the environment.
    """
    dotenv_path = Path.cwd() / ".env"
    if not dotenv_path.is_file():
        return
    try:
        for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value
    except OSError:
        # Silently ignore unreadable .env files; env vars remain usable.
        pass


@dataclass
class Config:
    """Mutable runtime configuration for the assistant."""

    provider: str = "ollama"
    model: str = "llama3"
    thinking: str = "medium"
    tools_enabled: bool = True
    allow_shell: bool = False
    ollama_host: str = "http://localhost:11434"
    openrouter_model: str = "deepseek/deepseek-chat"
    ollama_model: str = "llama3"
    # Integration feature flags (persisted)
    github_enabled: bool = False
    gmail_enabled: bool = False
    # Proxy URL for OpenRouter requests e.g. socks5://127.0.0.1:1080
    proxy_url: str = ""
    # API keys — never persisted to disk; sourced from environment only.
    _openrouter_api_key: Optional[str] = field(default=None, repr=False)

    # ----- persistence -------------------------------------------------
    @classmethod
    def load(cls) -> "Config":
        _load_dotenv()
        data: Dict[str, Any] = {}
        if CONFIG_PATH.is_file():
            try:
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                data = {}

        cfg = cls()
        for key in (
            "provider",
            "model",
            "thinking",
            "tools_enabled",
            "allow_shell",
            "ollama_host",
            "openrouter_model",
            "ollama_model",
            "github_enabled",
            "gmail_enabled",
            "proxy_url",
        ):
            if key in data:
                setattr(cfg, key, data[key])

        # Environment overrides take precedence for runtime values.
        cfg.ollama_host = os.environ.get("OLLAMA_HOST", cfg.ollama_host)
        env_provider = os.environ.get("RAST_PROVIDER")
        if env_provider in VALID_PROVIDERS:
            cfg.provider = env_provider
        env_model = os.environ.get("RAST_MODEL")
        if env_model:
            cfg.model = env_model

        # Keep per-provider model memory consistent with active model.
        if cfg.provider == "ollama":
            cfg.model = cfg.model or cfg.ollama_model
        else:
            cfg.model = cfg.model or cfg.openrouter_model

        cfg._openrouter_api_key = os.environ.get("OPENROUTER_API_KEY")
        # Auto-enable integrations if tokens are present in environment.
        if os.environ.get("GITHUB_TOKEN"):
            cfg.github_enabled = True
        if os.environ.get("GMAIL_ACCESS_TOKEN"):
            cfg.gmail_enabled = True
        # Proxy: env vars take precedence over saved config.
        env_proxy = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or os.environ.get("HTTP_PROXY") or ""
        if env_proxy:
            cfg.proxy_url = env_proxy
        return cfg

    def save(self) -> None:
        CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        data = {
            "provider": self.provider,
            "model": self.model,
            "thinking": self.thinking,
            "tools_enabled": self.tools_enabled,
            "allow_shell": self.allow_shell,
            "ollama_host": self.ollama_host,
            "openrouter_model": self.openrouter_model,
            "ollama_model": self.ollama_model,
            "github_enabled": self.github_enabled,
            "gmail_enabled": self.gmail_enabled,
            "proxy_url": self.proxy_url,
        }
        CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")

    # ----- helpers -----------------------------------------------------
    @property
    def openrouter_api_key(self) -> Optional[str]:
        # Always read the freshest value from the environment.
        return os.environ.get("OPENROUTER_API_KEY", self._openrouter_api_key)

    def set_provider(self, provider: str) -> None:
        if provider not in VALID_PROVIDERS:
            raise ValueError(
                f"Invalid provider '{provider}'. Choose from {VALID_PROVIDERS}."
            )
        # Remember the current model for the outgoing provider.
        if self.provider == "ollama":
            self.ollama_model = self.model
        else:
            self.openrouter_model = self.model
        self.provider = provider
        # Restore the remembered model for the incoming provider.
        self.model = self.ollama_model if provider == "ollama" else self.openrouter_model
        self.save()

    def set_model(self, model: str) -> None:
        self.model = model
        if self.provider == "ollama":
            self.ollama_model = model
        else:
            self.openrouter_model = model
        self.save()

    def set_thinking(self, level: str) -> None:
        if level not in VALID_THINKING:
            raise ValueError(
                f"Invalid thinking level '{level}'. Choose from {VALID_THINKING}."
            )
        self.thinking = level
        self.save()

    def set_tools(self, enabled: bool) -> None:
        self.tools_enabled = enabled
        self.save()

    def set_openrouter_key(self, key: str) -> None:
        """Set the OpenRouter API key in the live environment (never written to disk)."""
        os.environ["OPENROUTER_API_KEY"] = key
        self._openrouter_api_key = key

    def set_ollama_host(self, host: str) -> None:
        self.ollama_host = host
        os.environ["OLLAMA_HOST"] = host
        self.save()

    def set_proxy(self, url: str) -> None:
        """Set (or clear) the proxy URL for OpenRouter requests."""
        self.proxy_url = url
        if url:
            os.environ["HTTPS_PROXY"] = url
            os.environ["HTTP_PROXY"] = url
        else:
            os.environ.pop("HTTPS_PROXY", None)
            os.environ.pop("HTTP_PROXY", None)
        self.save()

    def set_integration_token(self, service: str, token: str) -> None:
        """Store an integration token in the live environment (never on disk)."""
        env_map = {
            "github": "GITHUB_TOKEN",
            "gmail": "GMAIL_ACCESS_TOKEN",
        }
        if service not in env_map:
            raise ValueError(f"Unknown integration '{service}'. Choose from: {list(env_map)}.")
        os.environ[env_map[service]] = token
        if service == "github":
            self.github_enabled = True
        elif service == "gmail":
            self.gmail_enabled = True
        self.save()

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("_openrouter_api_key", None)
        d["openrouter_api_key_present"] = bool(self.openrouter_api_key)
        return d
