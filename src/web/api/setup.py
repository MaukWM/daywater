"""Setup wizard routes — API key testing, Ghidra init, setup completion."""

from __future__ import annotations

from fastapi import APIRouter, BackgroundTasks
from fastapi.responses import StreamingResponse

from src.core.config import web_settings

router = APIRouter()


@router.post("/api/setup/test-key")
async def test_api_key(body: dict) -> dict:  # type: ignore[type-arg]
    """Test an API key by making a minimal inference call."""
    import os

    key = body.get("openai_api_key", "").strip()
    model = body.get("model", "openai/gpt-5.5").strip()

    if not key:
        return {"ok": False, "error": "No API key provided"}

    # Set key temporarily for the test
    old_key = os.environ.get("OPENAI_API_KEY")
    os.environ["OPENAI_API_KEY"] = key

    try:
        import openai

        client = openai.OpenAI(api_key=key)
        client.models.list()
        return {"ok": True}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
    finally:
        if old_key is not None:
            os.environ["OPENAI_API_KEY"] = old_key
        elif "OPENAI_API_KEY" in os.environ:
            del os.environ["OPENAI_API_KEY"]


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
