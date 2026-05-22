"""Savestate CRUD, screenshot, and savestate-level findings routes."""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import FileResponse

from src.findings import FindingsStore
from src.web.api.deps import _get_project, _get_savestate
from src.web.uploads import save_savestate_to_project

router = APIRouter()


# ── Savestate CRUD (project level) ───────────────────────────────────── #


@router.post("/api/projects/{project_id}/savestates/upload")
async def upload_savestate(project_id: str, file: UploadFile, name: str = "") -> dict:  # type: ignore[type-arg]
    project = _get_project(project_id)

    tmp = Path(tempfile.mktemp(suffix=".sav", prefix="daywater_upload_"))
    size = 0
    with tmp.open("wb") as f:
        while chunk := await file.read(1 << 20):
            f.write(chunk)
            size += len(chunk)

    try:
        ss = save_savestate_to_project(project, tmp, size, name=name)
    except ValueError as e:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, str(e))
    return ss.status_dict()


@router.get("/api/projects/{project_id}/savestates")
async def list_savestates(project_id: str) -> list[dict]:  # type: ignore[type-arg]
    project = _get_project(project_id)
    result = []
    for cfg in project.list_savestates():
        ss = project.get_savestate(cfg.savestate_id)
        findings_count = 0
        if ss:
            fs = FindingsStore.load(ss.root)
            findings_count = len(fs.findings)
        result.append({
            "savestate_id": cfg.savestate_id,
            "name": cfg.name,
            "notes": cfg.notes,
            "created_at": cfg.created_at,
            "has_screenshot": ss.screenshot_path.exists() if ss else False,
            "findings_count": findings_count,
        })
    return result


@router.get("/api/projects/{project_id}/savestates/{savestate_id}")
async def get_savestate(project_id: str, savestate_id: str) -> dict:  # type: ignore[type-arg]
    project = _get_project(project_id)
    ss = project.get_savestate(savestate_id)
    if ss is None:
        raise HTTPException(404, f"Savestate {savestate_id} not found")
    return ss.status_dict()


@router.post("/api/projects/{project_id}/savestates/{savestate_id}/notes")
async def update_savestate_notes(project_id: str, savestate_id: str, body: dict) -> dict[str, bool]:  # type: ignore[type-arg]
    project = _get_project(project_id)
    ss = project.get_savestate(savestate_id)
    if ss is None:
        raise HTTPException(404, f"Savestate {savestate_id} not found")
    if "name" in body:
        ss.config.name = body["name"]
    if "notes" in body:
        ss.config.notes = body["notes"]
    ss.save()
    return {"ok": True}


@router.delete("/api/projects/{project_id}/savestates/{savestate_id}")
async def delete_savestate(project_id: str, savestate_id: str) -> dict[str, bool]:
    project = _get_project(project_id)
    ss = project.get_savestate(savestate_id)
    if ss is None:
        raise HTTPException(404, f"Savestate {savestate_id} not found")
    shutil.rmtree(ss.root, ignore_errors=True)
    return {"ok": True}


@router.post("/api/projects/{project_id}/savestates/{savestate_id}/render-screenshot")
async def render_savestate_screenshot(project_id: str, savestate_id: str) -> dict:  # type: ignore[type-arg]
    """Render a screenshot from a savestate by booting Dolphin. Caches the result."""
    project = _get_project(project_id)
    ss = project.get_savestate(savestate_id)
    if ss is None:
        raise HTTPException(404, f"Savestate {savestate_id} not found")
    if not ss.savestate_path.exists():
        raise HTTPException(404, "Savestate file missing")

    from src.web.runner import run_capture_frame
    from src.web.uploads import save_screenshot_to_savestate

    frame_path = await run_capture_frame(ss.savestate_path, project.iso_path)
    save_screenshot_to_savestate(ss, frame_path)
    return {
        "ok": True,
        "screenshot_url": f"/api/projects/{project_id}/savestates/{savestate_id}/screenshot",
    }


@router.get("/api/projects/{project_id}/savestates/{savestate_id}/screenshot")
async def get_savestate_screenshot(project_id: str, savestate_id: str) -> FileResponse:
    """Serve the cached screenshot for a savestate."""
    project = _get_project(project_id)
    ss = project.get_savestate(savestate_id)
    if ss is None:
        raise HTTPException(404, f"Savestate {savestate_id} not found")
    if not ss.screenshot_path.exists():
        raise HTTPException(404, "No screenshot rendered yet — use render-screenshot first")
    return FileResponse(ss.screenshot_path, media_type="image/png")


# ── Savestate findings ───────────────────────────────────────────────── #


@router.get("/api/projects/{project_id}/savestates/{savestate_id}/findings")
async def get_savestate_findings(project_id: str, savestate_id: str) -> list[dict]:  # type: ignore[type-arg]
    _, ss = _get_savestate(project_id, savestate_id)
    fs = FindingsStore.load(ss.root)
    from dataclasses import asdict

    return [asdict(f) for f in fs.list_all()]


@router.post("/api/projects/{project_id}/savestates/{savestate_id}/findings")
async def add_savestate_finding(project_id: str, savestate_id: str, body: dict) -> dict:  # type: ignore[type-arg]
    _, ss = _get_savestate(project_id, savestate_id)
    fs = FindingsStore.load(ss.root)
    f = fs.add(
        kind=body.get("kind", "address"),
        label=body.get("label", ""),
        detail=body.get("detail", ""),
        address=body.get("address", ""),
        source_task=body.get("source_task", ""),
    )
    from dataclasses import asdict

    return asdict(f)


@router.delete("/api/projects/{project_id}/savestates/{savestate_id}/findings/{finding_id}")
async def delete_savestate_finding(
    project_id: str, savestate_id: str, finding_id: str,
) -> dict[str, bool]:
    _, ss = _get_savestate(project_id, savestate_id)
    fs = FindingsStore.load(ss.root)
    if not fs.remove(finding_id):
        raise HTTPException(404, f"Finding {finding_id} not found")
    return {"ok": True}


@router.delete("/api/projects/{project_id}/savestates/{savestate_id}/findings")
async def clear_savestate_findings(
    project_id: str, savestate_id: str,
) -> dict[str, bool]:
    """Delete all findings for a savestate."""
    _, ss = _get_savestate(project_id, savestate_id)
    fs = FindingsStore.load(ss.root)
    fs.findings.clear()
    fs._flush()
    return {"ok": True}
