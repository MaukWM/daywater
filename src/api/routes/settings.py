"""Settings routes — model config management."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter

from src.core.config import PROVIDER_ENV_VARS, settings, web_settings

router = APIRouter()

# Providers we surface in the model catalog UI.
_UI_PROVIDERS = [
    "openai", "anthropic", "gemini", "groq", "mistral",
    "together_ai", "fireworks_ai", "openrouter", "deepinfra", "xai",
]


# ── Settings CRUD ────────────────────────────────────────────────────── #


@router.get("/api/settings")
async def get_settings() -> dict:  # type: ignore[type-arg]
    """Return current settings including model configs (keys masked)."""
    web_settings.load()
    active = web_settings.active_config()
    return {
        "model_configs": web_settings.model_configs_masked(),
        "active_model_config": web_settings.active_config_id(),
        "active_model": active.get("model", "") if active else "",
        "setup_complete": web_settings.get("setup_complete", False),
        "ghidra_initialized": web_settings.get("ghidra_initialized", False),
        "demo": settings.DEMO,
        "inspect_url": os.environ.get("INSPECT_PUBLIC_URL", ""),
    }


@router.post("/api/settings/configs")
async def add_model_config(body: dict) -> dict[str, Any]:  # type: ignore[type-arg]
    """Add a new model configuration."""
    web_settings.load()
    name = body.get("name", "").strip()
    model = body.get("model", "").strip()
    api_key = body.get("api_key", "").strip()
    base_url = body.get("base_url", "").strip()

    if not name or not model:
        return {"ok": False, "error": "Name and model are required."}

    config = web_settings.add_model_config(
        name=name, model=model, api_key=api_key, base_url=base_url,
    )
    web_settings.save()
    web_settings.apply_to_env()
    return {"ok": True, "id": config["id"]}


@router.delete("/api/settings/configs/{config_id}")
async def delete_model_config(config_id: str) -> dict[str, bool]:
    """Remove a model configuration."""
    web_settings.load()
    removed = web_settings.remove_model_config(config_id)
    if removed:
        web_settings.save()
        web_settings.apply_to_env()
    return {"ok": removed}


@router.post("/api/settings/configs/{config_id}/activate")
async def activate_model_config(config_id: str) -> dict[str, bool]:
    """Set a model configuration as the active default."""
    web_settings.load()
    ok = web_settings.set_active_config(config_id)
    if ok:
        web_settings.save()
        web_settings.apply_to_env()
    return {"ok": ok}


# ── Model catalog ────────────────────────────────────────────────────── #


@router.get("/api/settings/models")
async def list_models() -> dict[str, Any]:
    """Return multimodal + tool-calling models grouped by provider.

    Uses litellm's ``model_cost`` map, filtered to vision-capable models
    from the providers we surface in the UI.
    """
    import litellm

    grouped: dict[str, list[dict[str, Any]]] = {}
    for model_key, info in litellm.model_cost.items():
        if model_key == "sample_spec":
            continue
        if not info.get("supports_vision"):
            continue
        if not info.get("supports_function_calling"):
            continue
        provider = info.get("litellm_provider", "")
        if provider not in _UI_PROVIDERS:
            continue
        mode = info.get("mode", "")
        if mode and mode != "chat":
            continue

        if provider not in grouped:
            grouped[provider] = []
        grouped[provider].append({
            "id": model_key,
            "max_input_tokens": info.get("max_input_tokens", 0),
            "max_output_tokens": info.get("max_output_tokens", info.get("max_tokens", 0)),
            "input_cost_per_1k": round((info.get("input_cost_per_token", 0) or 0) * 1000, 4),
            "output_cost_per_1k": round((info.get("output_cost_per_token", 0) or 0) * 1000, 4),
        })

    for provider in grouped:
        grouped[provider].sort(key=lambda m: m["id"])

    return {
        "providers": sorted(grouped.keys()),
        "models": grouped,
        "env_vars": PROVIDER_ENV_VARS,
    }
