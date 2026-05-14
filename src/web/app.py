"""FastAPI application — serves the API and static frontend."""

from __future__ import annotations

import asyncio
import shutil
import tempfile
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from src.web.events import stream_events
from src.web.mask import save_mask
from src.web.sessions import SessionState, SessionStore
from src.web.uploads import save_iso, save_reference_frame, save_savestate, save_screenshot

app = FastAPI(title="Spectre", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Session store — configurable root for dev vs Docker.
_sessions_root = Path("/app/sessions") if Path("/app/sessions").exists() else Path("./sessions")
store = SessionStore(_sessions_root)


def _get_session(session_id: str):  # type: ignore[no-untyped-def]
    session = store.get(session_id)
    if session is None:
        raise HTTPException(404, f"Session {session_id} not found")
    return session


# ── Session CRUD ──────────────────────────────────────────────────────── #


@app.post("/api/session")
async def create_session() -> dict[str, str]:
    session = store.create()
    return {"session_id": session.session_id}


@app.get("/api/session/{session_id}/status")
async def get_status(session_id: str) -> dict:  # type: ignore[type-arg]
    session = _get_session(session_id)
    return session.status_dict()


@app.get("/api/sessions")
async def list_sessions() -> list[dict]:  # type: ignore[type-arg]
    return [
        {"session_id": s.session_id, "state": s.state, "game_id": s.game_id, "created_at": s.created_at}
        for s in store.list_sessions()
    ]


@app.delete("/api/session/{session_id}")
async def delete_session(session_id: str) -> dict[str, bool]:
    session = _get_session(session_id)
    shutil.rmtree(session.root, ignore_errors=True)
    return {"ok": True}


# ── File uploads ──────────────────────────────────────────────────────── #


@app.post("/api/session/{session_id}/upload/iso")
async def upload_iso(session_id: str, file: UploadFile, background_tasks: BackgroundTasks) -> dict:  # type: ignore[type-arg]
    session = _get_session(session_id)
    if session.state not in (SessionState.CREATED,):
        raise HTTPException(400, f"Cannot upload ISO in state {session.state}")

    # Stream upload to temp file.
    tmp = Path(tempfile.mktemp(suffix=".iso", prefix="spectre_upload_"))
    size = 0
    with tmp.open("wb") as f:
        while chunk := await file.read(1 << 20):
            f.write(chunk)
            size += len(chunk)

    try:
        result = save_iso(session, tmp, size)
    except ValueError as e:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, str(e))

    # Kick off survey in background.
    from src.web.runner import run_survey

    async def _survey() -> None:
        s = _get_session(session_id)
        try:
            await run_survey(s)
        except Exception:
            pass  # logged inside run_survey

    background_tasks.add_task(_survey)

    return result


@app.post("/api/session/{session_id}/upload/savestate")
async def upload_savestate(session_id: str, file: UploadFile) -> dict:  # type: ignore[type-arg]
    session = _get_session(session_id)
    if session.state != SessionState.ISO_UPLOADED:
        raise HTTPException(400, f"Cannot upload savestate in state {session.state}")

    tmp = Path(tempfile.mktemp(suffix=".sav", prefix="spectre_upload_"))
    size = 0
    with tmp.open("wb") as f:
        while chunk := await file.read(1 << 20):
            f.write(chunk)
            size += len(chunk)

    try:
        result = save_savestate(session, tmp, size)
    except ValueError as e:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, str(e))
    return result


@app.post("/api/session/{session_id}/upload/screenshot")
async def upload_screenshot(session_id: str, file: UploadFile) -> dict:  # type: ignore[type-arg]
    session = _get_session(session_id)
    if session.state != SessionState.SAVESTATE_UPLOADED:
        raise HTTPException(400, f"Cannot upload screenshot in state {session.state}")

    tmp = Path(tempfile.mktemp(suffix=".png", prefix="spectre_upload_"))
    size = 0
    with tmp.open("wb") as f:
        while chunk := await file.read(1 << 20):
            f.write(chunk)
            size += len(chunk)

    try:
        result = save_screenshot(session, tmp, size)
    except ValueError as e:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, str(e))
    return result


# ── Capture frame from Dolphin ────────────────────────────────────────── #


@app.post("/api/session/{session_id}/capture")
async def capture_frame(session_id: str) -> dict:  # type: ignore[type-arg]
    session = _get_session(session_id)
    if session.state != SessionState.SAVESTATE_UPLOADED:
        raise HTTPException(400, f"Cannot capture in state {session.state}")

    from src.web.runner import run_capture_frame

    frame_path = await run_capture_frame(session)
    save_reference_frame(session, frame_path)
    return {"ok": True, "frame_url": f"/api/session/{session_id}/files/reference.png"}


# ── Mask ──────────────────────────────────────────────────────────────── #


@app.post("/api/session/{session_id}/mask")
async def submit_mask(session_id: str, file: UploadFile) -> dict:  # type: ignore[type-arg]
    session = _get_session(session_id)
    if session.state != SessionState.FRAME_READY:
        raise HTTPException(400, f"Cannot submit mask in state {session.state}")

    raw_bytes = await file.read()
    try:
        result = save_mask(session, raw_bytes)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # Auto-transition to READY if survey is complete.
    if session.config.survey_complete:
        session.transition(SessionState.READY)

    return result


# ── Config update ─────────────────────────────────────────────────────── #


@app.post("/api/session/{session_id}/config")
async def update_config(session_id: str, body: dict) -> dict[str, bool]:  # type: ignore[type-arg]
    session = _get_session(session_id)
    for key in ("hint", "run_seconds", "verify_budget", "hud_min_mean", "preserve_max_mean"):
        if key in body:
            setattr(session.config, key, body[key])
    session.save()
    return {"ok": True}


# ── Agent run ─────────────────────────────────────────────────────────── #


@app.post("/api/session/{session_id}/run")
async def start_run(session_id: str, background_tasks: BackgroundTasks) -> dict[str, bool]:  # type: ignore[type-arg]
    session = _get_session(session_id)
    if session.state != SessionState.READY:
        raise HTTPException(400, f"Cannot start run in state {session.state}")

    from src.web.runner import run_agent

    async def _run() -> None:
        s = _get_session(session_id)
        await run_agent(s)

    background_tasks.add_task(_run)
    return {"ok": True}


# ── SSE event stream ──────────────────────────────────────────────────── #


@app.get("/api/session/{session_id}/events")
async def event_stream(session_id: str) -> StreamingResponse:
    session = _get_session(session_id)
    return StreamingResponse(
        stream_events(session),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Results ───────────────────────────────────────────────────────────── #


@app.get("/api/session/{session_id}/result")
async def get_result(session_id: str) -> dict:  # type: ignore[type-arg]
    session = _get_session(session_id)
    if session.state not in (SessionState.DONE, SessionState.FAILED):
        raise HTTPException(400, f"No result yet (state: {session.state})")
    return {
        "verdict": session.config.result_verdict,
        "gecko": session.config.result_gecko,
        "hud_mean": session.config.result_hud_mean,
        "preserve_mean": session.config.result_preserve_mean,
        "has_frame": session.result_frame_path.exists(),
    }


@app.get("/api/session/{session_id}/result.gecko")
async def download_gecko(session_id: str) -> FileResponse:
    session = _get_session(session_id)
    if not session.result_gecko_path.exists():
        raise HTTPException(404, "No gecko code found")
    return FileResponse(
        session.result_gecko_path,
        media_type="text/plain",
        filename=f"{session.config.game_id}_hud_off.gecko",
    )


# ── Serve session files (reference, mask, result frame) ───────────────── #


@app.get("/api/session/{session_id}/files/{filename}")
async def get_session_file(session_id: str, filename: str) -> FileResponse:
    session = _get_session(session_id)
    # Whitelist serveable files.
    allowed = {"reference.png", "mask.png", "result_frame.png", "config.json"}
    if filename not in allowed:
        raise HTTPException(403, f"File {filename} not serveable")
    path = session.root / filename
    if not path.exists():
        raise HTTPException(404, f"File {filename} not found")
    return FileResponse(path)


# ── Static frontend ───────────────────────────────────────────────────── #

_static_dir = Path(__file__).parent / "static"
if _static_dir.exists():
    app.mount("/", StaticFiles(directory=str(_static_dir), html=True), name="static")


# ── Entry point ───────────────────────────────────────────────────────── #


def main() -> None:
    import subprocess
    import sys

    import uvicorn

    # Launch Inspect AI viewer on :7575 in background for fine-grained run inspection.
    inspect_proc = None
    try:
        inspect_proc = subprocess.Popen(
            ["inspect", "view", "--host", "0.0.0.0", "--port", "7575", "--log-dir", "/app/logs"],
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
