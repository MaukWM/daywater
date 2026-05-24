"""FastAPI application — serves the API and static frontend."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from src.core.config import settings, web_settings
from src.core.paths import logs_root
from src.api.routes.knowledge import router as knowledge_router
from src.api.routes.processes import router as processes_router
from src.api.routes.projects import router as projects_router
from src.api.routes.savestates import router as savestates_router
from src.api.routes.schema import router as schema_router
from src.api.routes.settings import router as settings_router
from src.api.routes.setup import router as setup_router
from src.api.routes.tasks import router as tasks_router

app = FastAPI(title="Daywater", version="0.2.0")

# Apply persisted settings to env on import (app startup)
if not settings.DEMO:
    web_settings.apply_to_env()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Demo mode (read-only) ──────────────────────────────────────────── #

if settings.DEMO:

    @app.middleware("http")
    async def demo_read_only(request: Request, call_next):  # type: ignore[no-untyped-def]
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            return JSONResponse(
                status_code=403,
                content={"detail": "This is a read-only demo instance."},
            )
        return await call_next(request)


# ── Include routers ──────────────────────────────────────────────────── #

app.include_router(projects_router)
app.include_router(tasks_router)
app.include_router(savestates_router)
app.include_router(knowledge_router)
app.include_router(schema_router)
app.include_router(settings_router)
app.include_router(setup_router)
app.include_router(processes_router)

# ── Static frontend ─────────────────────────────────────────────────── #

_frontend_dir = Path(__file__).resolve().parent.parent.parent / "frontend"
if _frontend_dir.exists():
    app.mount("/", StaticFiles(directory=str(_frontend_dir), html=True), name="frontend")


# ── Entry point ──────────────────────────────────────────────────────── #


def main() -> None:
    import subprocess

    import uvicorn

    # Launch Inspect AI viewer on :7575 in background for fine-grained run inspection.
    inspect_proc = None
    try:
        inspect_proc = subprocess.Popen(
            ["inspect", "view", "--host", "0.0.0.0", "--port", "7575", "--log-dir", str(logs_root())],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass  # inspect view is optional; web UI still works without it

    try:
        uvicorn.run(
            "src.api.app:app",
            host="0.0.0.0",
            port=7860,
            reload=False,
        )
    finally:
        if inspect_proc:
            inspect_proc.terminate()


if __name__ == "__main__":
    main()
