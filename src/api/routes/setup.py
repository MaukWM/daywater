"""Setup wizard routes — API key testing, Ghidra init, setup completion."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import StreamingResponse

from src.core.config import env_var_for_provider, provider_from_model, web_settings  # noqa: F401

router = APIRouter()


@router.post("/api/setup/test-key")
async def test_api_key(body: dict) -> dict:  # type: ignore[type-arg]
    """Test an API key via a minimal LiteLLM completion call."""
    import os

    key = body.get("api_key", "").strip()
    model = body.get("model", "").strip()
    base_url = body.get("base_url", "").strip()
    provider = body.get("provider", "").strip() or (provider_from_model(model) if model else "")

    if not key:
        return {"ok": False, "error": "No API key provided"}
    if not provider or not model:
        return {"ok": False, "error": "Cannot detect provider — set a model like openai/gpt-5.5"}

    env_var = env_var_for_provider(provider)

    # Temporarily set the key for the test.
    old_val = os.environ.get(env_var) if env_var else None
    if env_var:
        os.environ[env_var] = key

    try:
        import litellm

        kwargs: dict[str, object] = {
            "model": model,
            "messages": [{"role": "user", "content": "say ok"}],
            "max_tokens": 100,
        }
        if base_url:
            kwargs["base_url"] = base_url
        litellm.completion(**kwargs)  # type: ignore[arg-type]
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        if env_var:
            if old_val is not None:
                os.environ[env_var] = old_val
            else:
                os.environ.pop(env_var, None)


@router.post("/api/setup/init-ghidra")
async def init_ghidra(background_tasks: BackgroundTasks) -> dict[str, bool]:
    """Start Ghidra JVM initialization in the background."""
    from src.agent.runner import run_ghidra_init

    async def _init() -> None:
        try:
            await run_ghidra_init()
            web_settings.load()
            web_settings.set("ghidra_initialized", True)
            web_settings.save()
        except Exception:
            pass

    background_tasks.add_task(_init)
    return {"ok": True}


@router.get("/api/setup/init-ghidra/events")
async def ghidra_init_events() -> StreamingResponse:
    """SSE stream of Ghidra init progress."""
    from src.agent.runner import stream_ghidra_init_events

    return StreamingResponse(
        stream_ghidra_init_events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/api/setup/complete")
async def complete_setup() -> dict[str, bool]:
    """Mark setup as complete."""
    web_settings.load()
    web_settings.set("setup_complete", True)
    web_settings.save()
    web_settings.apply_to_env()
    return {"ok": True}
