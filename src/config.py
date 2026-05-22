"""Application configuration.

``Settings`` — environment-derived config (DEBUG, LOG_LEVEL, etc.).
``WebSettings`` — persisted JSON settings (API key, model, setup state).
"""

from __future__ import annotations

import json
import os
from pathlib import Path

from dotenv import load_dotenv

from src.paths import sessions_root


class Settings:
    def __init__(self) -> None:
        load_dotenv()

        self.DEBUG: bool = os.getenv("DEBUG", "false").lower() in ("true", "1", "t", "yes")
        self.LOG_LEVEL: str = os.getenv("LOG_LEVEL", "DEBUG" if self.DEBUG else "INFO")
        self.LOG_FORMAT: str = os.getenv("LOG_FORMAT", "console")


settings = Settings()


class WebSettings:
    """Persisted web UI settings (API key, model, setup/Ghidra state).

    Stored as a JSON file under the sessions root. Load/save are explicit
    so callers control when disk I/O happens.
    """

    def __init__(self, path: Path | None = None) -> None:
        self._path = path or (sessions_root() / ".daywater_settings.json")
        self._data: dict[str, str | bool] = {}
        self.load()

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

    def get(self, key: str, default: str | bool = "") -> str | bool:
        return self._data.get(key, default)

    def set(self, key: str, value: str | bool) -> None:
        self._data[key] = value

    def pop(self, key: str) -> None:
        self._data.pop(key, None)

    def apply_to_env(self) -> None:
        """Push stored settings into environment variables."""
        if self.get("openai_api_key"):
            os.environ["OPENAI_API_KEY"] = str(self.get("openai_api_key"))
        if self.get("model"):
            os.environ["INSPECT_EVAL_MODEL"] = str(self.get("model"))


web_settings = WebSettings()
