"""Settings routes — API key management and model configuration."""

from __future__ import annotations

from fastapi import APIRouter

from src.core.config import settings, web_settings

router = APIRouter()


@router.get("/api/settings")
async def get_settings() -> dict:  # type: ignore[type-arg]
    """Return current settings (API key is masked)."""
    web_settings.load()
    key = str(web_settings.get("openai_api_key", ""))
    return {
        "openai_api_key_set": bool(key),
        "openai_api_key_preview": f"...{key[-6:]}" if len(key) > 6 else ("***" if key else ""),
        "model": web_settings.get("model", ""),
        "setup_complete": web_settings.get("setup_complete", False),
        "ghidra_initialized": web_settings.get("ghidra_initialized", False),
        "demo": settings.DEMO,
    }


@router.post("/api/settings")
async def update_settings(body: dict) -> dict[str, bool]:  # type: ignore[type-arg]
    """Update settings. Applies immediately to environment."""
    import os

    web_settings.load()

    if "openai_api_key" in body:
        key = body["openai_api_key"].strip()
        if key:
            web_settings.set("openai_api_key", key)
            os.environ["OPENAI_API_KEY"] = key
        else:
            web_settings.pop("openai_api_key")
            os.environ.pop("OPENAI_API_KEY", None)

    if "model" in body:
        model = body["model"].strip()
        if model:
            web_settings.set("model", model)
            os.environ["INSPECT_EVAL_MODEL"] = model
        else:
            web_settings.pop("model")
            os.environ.pop("INSPECT_EVAL_MODEL", None)

    web_settings.save()
    return {"ok": True}
