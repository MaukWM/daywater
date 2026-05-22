"""FastAPI application — serves the API and static frontend."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.config import web_settings
from src.paths import logs_root
from src.web.api.knowledge import router as knowledge_router
from src.web.api.processes import router as processes_router
from src.web.api.projects import router as projects_router
from src.web.api.savestates import router as savestates_router
from src.web.api.schema import router as schema_router
from src.web.api.settings import router as settings_router
from src.web.api.setup import router as setup_router
from src.web.api.tasks import router as tasks_router

app = FastAPI(title="Daywater", version="0.2.0")

# Apply persisted settings to env on import (app startup)
web_settings.apply_to_env()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

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

_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")


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
            "src.web.app:app",
            host="0.0.0.0",
            port=7860,
            reload=False,
        )
    finally:
        if inspect_proc:
            inspect_proc.terminate()


if __name__ == "__main__":
    main()
