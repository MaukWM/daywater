"""Project CRUD, ISO upload, events, controller mapping, and disc contents routes."""

from __future__ import annotations

import re
import shutil
import tempfile
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile
from fastapi.responses import StreamingResponse

from src.core.ghidra import list_iso_files
from src.api.routes.deps import _get_project, store
from src.api.events import stream_events
from src.core.uploads import save_iso

router = APIRouter()


# ── Project CRUD ─────────────────────────────────────────────────────── #


@router.post("/api/projects")
async def create_project() -> dict[str, str]:
    project = store.create()
    return {"project_id": project.project_id}


@router.get("/api/projects")
async def list_projects() -> list[dict]:  # type: ignore[type-arg]
    return [
        {
            "project_id": p.project_id,
            "name": p.name,
            "game_id": p.game_id,
            "iso_sha1": p.iso_sha1,
            "iso_size": p.iso_size,
            "survey_complete": p.survey_complete,
            "survey_binaries_done": p.survey_binaries_done,
            "created_at": p.created_at,
        }
        for p in store.list_projects()
    ]


@router.get("/api/projects/{project_id}")
async def get_project(project_id: str) -> dict:  # type: ignore[type-arg]
    project = _get_project(project_id)
    return project.status_dict()


@router.post("/api/projects/{project_id}/name")
async def update_project_name(project_id: str, body: dict) -> dict[str, bool]:  # type: ignore[type-arg]
    project = _get_project(project_id)
    project.config.name = body.get("name", "").strip()
    project.save()
    return {"ok": True}


@router.delete("/api/projects/{project_id}")
async def delete_project(project_id: str) -> dict[str, bool]:
    project = _get_project(project_id)
    shutil.rmtree(project.root, ignore_errors=True)
    return {"ok": True}


# ── ISO Upload (project level) ──────────────────────────────────────── #


@router.post("/api/projects/{project_id}/upload/iso")
async def upload_iso(project_id: str, file: UploadFile, background_tasks: BackgroundTasks) -> dict:  # type: ignore[type-arg]
    project = _get_project(project_id)
    if project.config.game_id:
        raise HTTPException(400, "ISO already uploaded for this project")

    # Stream upload to temp file.
    tmp = Path(tempfile.mktemp(suffix=".iso", prefix="daywater_upload_"))
    size = 0
    with tmp.open("wb") as f:
        while chunk := await file.read(1 << 20):
            f.write(chunk)
            size += len(chunk)

    try:
        result = save_iso(project, tmp, size)
    except ValueError as e:
        tmp.unlink(missing_ok=True)
        raise HTTPException(400, str(e))

    # Kick off survey in background.
    from src.agent.runner import run_survey

    async def _survey() -> None:
        p = _get_project(project_id)
        try:
            await run_survey(p)
        except Exception:
            pass  # logged inside run_survey

    background_tasks.add_task(_survey)

    return result


@router.get("/api/projects/{project_id}/events")
async def project_event_stream(project_id: str) -> StreamingResponse:
    project = _get_project(project_id)
    return StreamingResponse(
        stream_events(project),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Controller Mapping (project level) ───────────────────────────────── #


@router.get("/api/projects/{project_id}/controller-mapping")
async def get_controller_mapping(project_id: str) -> dict:  # type: ignore[type-arg]
    from src.core.dolphin.controller_mapping import load_mapping

    project = _get_project(project_id)
    return load_mapping(project.root)


@router.post("/api/projects/{project_id}/controller-mapping")
async def update_controller_mapping(project_id: str, body: dict) -> dict[str, bool]:  # type: ignore[type-arg]
    from src.core.dolphin.controller_mapping import load_mapping, save_mapping

    project = _get_project(project_id)
    # Merge incoming data with existing mapping
    mapping = load_mapping(project.root)
    if "buttons" in body:
        for btn, desc in body["buttons"].items():
            if btn in mapping["buttons"]:
                mapping["buttons"][btn] = desc
    if "sticks" in body:
        for stick, data in body["sticks"].items():
            if stick in mapping["sticks"]:
                if isinstance(data, dict):
                    for key in ("description", "up", "down", "left", "right"):
                        if key in data:
                            mapping["sticks"][stick][key] = data[key]
    save_mapping(project.root, mapping)
    return {"ok": True}


# ── Disc contents ──────────────────────────────────────────────────── #


@router.get("/api/projects/{project_id}/disc-contents")
async def get_disc_contents(project_id: str) -> dict:  # type: ignore[type-arg]
    """Return the full ISO filesystem as a flat file list + analyzed binary info."""
    project = _get_project(project_id)
    if not project.iso_path.exists():
        raise HTTPException(404, "No ISO uploaded for this project")

    from src.core.ghidra.iso import read_header

    files = list_iso_files(project.iso_path)

    # boot.dol is not in the FST — add it as a synthetic entry from the disc header
    hdr = read_header(project.iso_path)
    dol_size = 0
    try:
        with project.iso_path.open("rb") as f:
            # DOL header: 7 text segments + 11 data segments, each with offset+addr+size
            # Total DOL size = max(offset + size) across all segments
            f.seek(hdr.dol_offset)
            dol_hdr = f.read(0x100)
            if len(dol_hdr) >= 0x100:
                max_end = 0
                for i in range(18):  # 7 text + 11 data segments
                    off = int.from_bytes(dol_hdr[i * 4 : i * 4 + 4], "big")
                    sz = int.from_bytes(dol_hdr[0x90 + i * 4 : 0x94 + i * 4], "big")
                    if off and sz:
                        max_end = max(max_end, off + sz)
                dol_size = max_end
    except Exception:
        pass

    file_list = [{"path": "boot.dol", "size": dol_size, "is_directory": False}]
    file_list.extend(
        {"path": f.path, "size": f.size, "is_directory": False}
        for f in files
    )

    # analyzed_binaries stored during survey: label -> {sha1, function_count}
    # Fallback for projects surveyed before this field existed: parse inventory_text
    analyzed_binaries = project.config.analyzed_binaries or {}
    if not analyzed_binaries and project.config.inventory_text:
        for line in project.config.inventory_text.splitlines():
            # Match lines like: "  boot.dol      3,613,184  f3bf225d...  11250  note"
            m = re.match(
                r"\s+(\S+)\s+[\d,]+\s+([0-9a-f]{40})\s+(\d+)",
                line,
            )
            if m:
                analyzed_binaries[m.group(1)] = {
                    "sha1": m.group(2),
                    "function_count": int(m.group(3)),
                }

    total_size = sum(f.size for f in files)

    return {
        "files": file_list,
        "analyzed_binaries": analyzed_binaries,
        "total_files": len(file_list),
        "total_size": total_size,
    }
