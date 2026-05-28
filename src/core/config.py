"""Application configuration.

``Settings`` — environment-derived config (DEBUG, LOG_LEVEL, etc.).
``WebSettings`` — persisted JSON settings (model configs, setup state).
"""

from __future__ import annotations

import json
import os
import uuid
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from src.core.paths import sessions_root

# Maps Inspect AI provider prefix to the environment variable it reads.
PROVIDER_ENV_VARS: dict[str, str] = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
    "google": "GOOGLE_API_KEY",
    "groq": "GROQ_API_KEY",
    "together": "TOGETHER_API_KEY",
    "mistral": "MISTRAL_API_KEY",
    "openrouter": "OPENROUTER_API_KEY",
    "fireworks_ai": "FIREWORKS_API_KEY",
}


def provider_from_model(model: str) -> str:
    """Extract the provider prefix from a model string like ``openai/gpt-5.5``."""
    return model.split("/")[0] if "/" in model else model


def env_var_for_provider(provider: str) -> str | None:
    """Return the environment variable name for *provider*, or ``None``."""
    return PROVIDER_ENV_VARS.get(provider)


def mask_key(key: str) -> str:
    """Mask an API key for display, showing only last 6 chars."""
    if len(key) > 6:
        return f"...{key[-6:]}"
    return "***" if key else ""


class Settings:
    def __init__(self) -> None:
        load_dotenv()

        self.DEBUG: bool = os.getenv("DEBUG", "false").lower() in ("true", "1", "t", "yes")
        self.LOG_LEVEL: str = os.getenv("LOG_LEVEL", "DEBUG" if self.DEBUG else "INFO")
        self.LOG_FORMAT: str = os.getenv("LOG_FORMAT", "console")
        self.DEMO: bool = os.getenv("DAYWATER_DEMO", "false").lower() in ("true", "1", "t", "yes")


settings = Settings()


class WebSettings:
    """Persisted web UI settings (model configs, setup/Ghidra state).

    Model configurations are stored as a list of dicts, each with::

        {"id": "...", "name": "...", "model": "provider/model",
         "api_key": "...", "base_url": ""}

    One config is marked active via ``active_model_config`` (an id).
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (sessions_root() / ".daywater_settings.json")
        self._data: dict[str, Any] = {}
        self.load()

    # ── persistence ──────────────────────────────────────────────────── #

    def load(self) -> None:
        """Read settings from disk."""
        if self._path.exists():
            try:
                self._data = json.loads(self._path.read_text())
            except (json.JSONDecodeError, ValueError):
                self._data = {}
        else:
            self._data = {}

    def save(self) -> None:
        """Atomically write settings to disk."""
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".tmp")
        try:
            tmp.write_text(json.dumps(self._data, indent=2))
            tmp.replace(self._path)
        except PermissionError:
            tmp.unlink(missing_ok=True)
            raise

    # ── generic accessors ────────────────────────────────────────────── #

    def get(self, key: str, default: Any = "") -> Any:
        return self._data.get(key, default)

    def set(self, key: str, value: Any) -> None:
        self._data[key] = value

    def pop(self, key: str) -> None:
        self._data.pop(key, None)

    # ── model config helpers ─────────────────────────────────────────── #

    def model_configs(self) -> list[dict[str, Any]]:
        configs = self._data.get("model_configs")
        if not isinstance(configs, list):
            self._data["model_configs"] = []
        return self._data["model_configs"]  # type: ignore[return-value]

    def active_config_id(self) -> str:
        return str(self._data.get("active_model_config", ""))

    def active_config(self) -> dict[str, Any] | None:
        cid = self.active_config_id()
        for c in self.model_configs():
            if c.get("id") == cid:
                return c
        return None

    def add_model_config(
        self, *, name: str, model: str, api_key: str = "", base_url: str = "",
    ) -> dict[str, Any]:
        """Add a new model config and return it."""
        config: dict[str, Any] = {
            "id": uuid.uuid4().hex[:12],
            "name": name,
            "model": model,
            "api_key": api_key,
            "base_url": base_url,
        }
        self.model_configs().append(config)
        # Auto-activate if it's the first one.
        if len(self.model_configs()) == 1:
            self._data["active_model_config"] = config["id"]
        return config

    def remove_model_config(self, config_id: str) -> bool:
        configs = self.model_configs()
        before = len(configs)
        self._data["model_configs"] = [c for c in configs if c.get("id") != config_id]
        # Clear active if we removed it.
        if self.active_config_id() == config_id:
            remaining = self.model_configs()
            self._data["active_model_config"] = remaining[0]["id"] if remaining else ""
        return len(self.model_configs()) < before

    def set_active_config(self, config_id: str) -> bool:
        for c in self.model_configs():
            if c.get("id") == config_id:
                self._data["active_model_config"] = config_id
                return True
        return False

    def model_configs_masked(self) -> list[dict[str, Any]]:
        """Return configs with API keys masked for the frontend."""
        out = []
        for c in self.model_configs():
            masked = dict(c)
            masked["api_key_preview"] = mask_key(c.get("api_key", ""))
            masked.pop("api_key", None)
            out.append(masked)
        return out

    # ── env export ───────────────────────────────────────────────────── #

    def apply_to_env(self) -> None:
        """Push the active model config into environment variables."""
        config = self.active_config()
        if not config:
            return

        model = config.get("model", "")
        api_key = config.get("api_key", "")
        base_url = config.get("base_url", "")
        provider = provider_from_model(model)

        if model:
            os.environ["INSPECT_EVAL_MODEL"] = model
        if api_key:
            env_var = env_var_for_provider(provider)
            if env_var:
                os.environ[env_var] = api_key
        if base_url:
            os.environ["OPENAI_BASE_URL"] = base_url
        elif "OPENAI_BASE_URL" in os.environ:
            # Clear stale base URL if the active config doesn't use one.
            del os.environ["OPENAI_BASE_URL"]


web_settings = WebSettings()
