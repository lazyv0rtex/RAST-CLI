"""Configuration management for Rast-CLI.

Settings are persisted to ``~/.config/rast-cli/config.json`` and may be
overridden by environment variables (optionally loaded from a local ``.env``).
"""

from __future__ import annotations

import base64
import json
import os
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Optional

CONFIG_DIR = Path(os.path.expanduser("~")) / ".config" / "rast-cli"
CONFIG_PATH = CONFIG_DIR / "config.json"
SESSION_PATH = CONFIG_DIR / "last_session.json"
HISTORY_PATH = CONFIG_DIR / "history.txt"


def _obfuscate(value: str) -> str:
    """Light obfuscation so the key isn't plain text in the config file."""
    return base64.b64encode(value.encode()).decode()


def _deobfuscate(value: str) -> str:
    try:
        return base64.b64decode(value.encode()).decode()
    except Exception:
        return value  # Already plain text (legacy)

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

    Looks for a ``.env`` file in the current working directory, then falls
    back to any path saved in the config, so keys load from anywhere.
    """
    candidates = [Path.cwd() / ".env"]
    # Also load from saved env_file_path in config (if any).
    try:
        raw = CONFIG_PATH.read_text(encoding="utf-8")
        saved = json.loads(raw).get("env_file_path", "")
        if saved:
            candidates.append(Path(saved))
    except Exception:
        pass

    def _load_file(dotenv_path: Path) -> None:
        try:
            for raw_line in dotenv_path.read_text(encoding="utf-8").splitlines():
                line = raw_line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k and k not in os.environ:
                    os.environ[k] = v
        except OSError:
            pass

    for dotenv_path in candidates:
        if dotenv_path.is_file():
            _load_file(dotenv_path)


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
    # Auto-commit file changes made by the agent
    autocommit: bool = False
    # Saved path to .env so it loads from anywhere
    env_file_path: str = ""
    # Persisted keys (obfuscated, not encrypted — stored in user-only config)
    _openrouter_api_key: Optional[str] = field(default=None, repr=False)
    _github_token: Optional[str] = field(default=None, repr=False)
    _gmail_token: Optional[str] = field(default=None, repr=False)

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
            "autocommit",
            "env_file_path",
        ):
            if key in data:
                setattr(cfg, key, data[key])

        # Load persisted keys (obfuscated in config).
        if "openrouter_key" in data and data["openrouter_key"]:
            cfg._openrouter_api_key = _deobfuscate(data["openrouter_key"])
            os.environ.setdefault("OPENROUTER_API_KEY", cfg._openrouter_api_key)
        if "github_token" in data and data["github_token"]:
            cfg._github_token = _deobfuscate(data["github_token"])
            os.environ.setdefault("GITHUB_TOKEN", cfg._github_token)
        if "gmail_token" in data and data["gmail_token"]:
            cfg._gmail_token = _deobfuscate(data["gmail_token"])
            os.environ.setdefault("GMAIL_ACCESS_TOKEN", cfg._gmail_token)

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

        # Env var always wins over saved key.
        env_key = os.environ.get("OPENROUTER_API_KEY")
        if env_key:
            cfg._openrouter_api_key = env_key
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
            "autocommit": self.autocommit,
            "env_file_path": self.env_file_path,
            # Persisted keys — obfuscated, not encrypted.
            "openrouter_key": _obfuscate(self._openrouter_api_key) if self._openrouter_api_key else "",
            "github_token": _obfuscate(self._github_token) if self._github_token else "",
            "gmail_token": _obfuscate(self._gmail_token) if self._gmail_token else "",
        }
        CONFIG_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
        # Restrict config file permissions so other users can't read it.
        try:
            CONFIG_PATH.chmod(0o600)
        except OSError:
            pass

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
        """Set the OpenRouter API key and persist it to config."""
        os.environ["OPENROUTER_API_KEY"] = key
        self._openrouter_api_key = key
        self.save()

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
        """Store an integration token in the environment and persist to config."""
        env_map = {
            "github": "GITHUB_TOKEN",
            "gmail": "GMAIL_ACCESS_TOKEN",
        }
        if service not in env_map:
            raise ValueError(f"Unknown integration '{service}'. Choose from: {list(env_map)}.")
        os.environ[env_map[service]] = token
        if service == "github":
            self.github_enabled = True
            self._github_token = token
        elif service == "gmail":
            self.gmail_enabled = True
            self._gmail_token = token
        self.save()

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d.pop("_openrouter_api_key", None)
        d["openrouter_api_key_present"] = bool(self.openrouter_api_key)
        return d
