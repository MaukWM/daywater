"""Task CRUD, capture, mask, config, run, events, results, and file serving routes."""

from __future__ import annotations

import shutil

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile
from fastapi.responses import FileResponse, StreamingResponse

from src.core.ghidra.notes import NotesStore
from src.core.knowledge import FindingsStore
from src.core.paths import binaries_cache
from src.web.api.deps import _get_project, _get_task
from src.web.events import stream_events
from src.core.mask import save_mask
from src.web.sessions import TaskState
from src.core.uploads import save_reference_frame

router = APIRouter()


# ── Presets ─────────────────────────────────────────────────────────── #


@router.get("/api/presets")
async def list_presets() -> list[dict]:  # type: ignore[type-arg]
    """List available task presets with their job specs."""
    from src.agent.presets import PRESET_DESCRIPTIONS, PRESETS

    return [
        {
            "name": name,
            "description": PRESET_DESCRIPTIONS.get(name, ""),
            "job_spec": spec.to_dict(),
        }
        for name, spec in PRESETS.items()
    ]


# ── Task CRUD ────────────────────────────────────────────────────────── #


@router.post("/api/projects/{project_id}/tasks")
async def create_task(project_id: str, body: dict | None = None) -> dict[str, str]:  # type: ignore[type-arg]
    project = _get_project(project_id)
    if not project.config.game_id:
        raise HTTPException(400, "Upload an ISO first")

    body = body or {}
    task_name = body.get("name", "").strip() or "Unnamed Task"

    if "preset" in body:
        task = project.create_task(preset=body["preset"], name=task_name)
    elif "job_spec" in body:
        task = project.create_task(job_spec_dict=body["job_spec"], name=task_name)
    else:
        raise HTTPException(400, "Either 'preset' or 'job_spec' is required")

    spec = task.config.get_job_spec()
    return {
        "task_id": task.task_id,
        "preset": task.config.preset_name,
        "goal_type": spec.goal_type.value,
        "needs_savestate": str(spec.needs_savestate).lower(),
        "needs_mask": str(spec.needs_mask).lower(),
    }


@router.get("/api/projects/{project_id}/tasks")
async def list_tasks(project_id: str) -> list[dict]:  # type: ignore[type-arg]
    project = _get_project(project_id)
    result = []
    for t in project.list_tasks():
        spec = t.get_job_spec()
        state = t.state
        result.append({
            "task_id": t.task_id,
            "name": t.name,
            "preset": t.preset_name,
            "goal_type": spec.goal_type.value,
            "state": state,
            "result_verdict": t.result_verdict,
            "created_at": t.created_at,
        })
    return result


@router.delete("/api/projects/{project_id}/tasks/{task_id}")
async def delete_task(project_id: str, task_id: str) -> dict:  # type: ignore[type-arg]
    project, task = _get_task(project_id, task_id)

    # Clean up findings created by this task (project-level)
    fs = FindingsStore.load(project.root)
    removed_findings = [f for f in fs.findings if f.source_task == task_id]
    for f in removed_findings:
        fs.remove(f.id)

    # Clean up savestate findings created by this task
    if task.config.savestate_id:
        ss = project.get_savestate(task.config.savestate_id)
        if ss is not None:
            ss_fs = FindingsStore.load(ss.root)
            ss_removed = [f for f in ss_fs.findings if f.source_task == task_id]
            for f in ss_removed:
                ss_fs.remove(f.id)

    # Clean up research docs created by this task
    from src.agent.tools.research import remove_research_docs_for_task

    removed_docs = remove_research_docs_for_task(project.root, task_id)

    # Clean up Ghidra renames/notes created by this task
    cache_root = binaries_cache()
    removed_renames = 0
    removed_notes = 0
    if cache_root.exists():
        for sha_dir in cache_root.iterdir():
            notes_path = sha_dir / "notes.json"
            if notes_path.exists():
                ns = NotesStore.load(sha_dir)
                r, n = ns.remove_for_task(task_id)
                removed_renames += r
                removed_notes += n

    # Delete the task directory itself
    shutil.rmtree(task.root, ignore_errors=True)

    return {
        "ok": True,
        "removed_findings": len(removed_findings),
        "removed_docs": len(removed_docs),
        "removed_renames": removed_renames,
        "removed_notes": removed_notes,
    }


@router.get("/api/projects/{project_id}/tasks/{task_id}")
async def get_task_status(project_id: str, task_id: str) -> dict:  # type: ignore[type-arg]
    project, task = _get_task(project_id, task_id)
    d = task.status_dict()
    d["survey_complete"] = project.config.survey_complete
    d["survey_binaries_done"] = project.config.survey_binaries_done
    d["survey_binaries_total"] = project.config.survey_binaries_total
    return d


# ── Task savestate selection ─────────────────────────────────────────── #


@router.post("/api/projects/{project_id}/tasks/{task_id}/select-savestate")
async def select_savestate(project_id: str, task_id: str, body: dict) -> dict:  # type: ignore[type-arg]
    project, task = _get_task(project_id, task_id)
    ss_id = body.get("savestate_id", "")
    if not ss_id:
        raise HTTPException(400, "savestate_id is required")
    ss = project.get_savestate(ss_id)
    if ss is None:
        raise HTTPException(404, f"Savestate {ss_id} not found")

    task.config.savestate_id = ss_id

    # If the savestate has a rendered screenshot, copy it as the task's
    # reference frame and skip straight to FRAME_READY.
    if ss.screenshot_path.exists():
        shutil.copy2(str(ss.screenshot_path), str(task.reference_path))
        task.transition(TaskState.FRAME_READY)
        return {"ok": True, "has_reference": True}

    task.transition(TaskState.SAVESTATE_UPLOADED)
    return {"ok": True, "has_reference": False}


# ── Capture frame from Dolphin ───────────────────────────────────────── #


@router.post("/api/projects/{project_id}/tasks/{task_id}/capture")
async def capture_frame(project_id: str, task_id: str) -> dict:  # type: ignore[type-arg]
    project, task = _get_task(project_id, task_id)
    # Allow capture from multiple states (fixes re-capture bug).
    if task.state not in (TaskState.SAVESTATE_UPLOADED, TaskState.FRAME_READY, TaskState.MASK_READY):
        raise HTTPException(400, f"Cannot capture in state {task.state}")

    ss = project.get_savestate(task.config.savestate_id)
    if ss is None:
        raise HTTPException(400, "No savestate selected for this task")

    from src.agent.runner import run_capture_frame

    frame_path = await run_capture_frame(ss.savestate_path, project.iso_path)
    save_reference_frame(task, frame_path)
    return {"ok": True, "frame_url": f"/api/projects/{project_id}/tasks/{task_id}/files/reference.png"}


# ── Mask ─────────────────────────────────────────────────────────────── #


@router.post("/api/projects/{project_id}/tasks/{task_id}/mask")
async def submit_mask(project_id: str, task_id: str, file: UploadFile) -> dict:  # type: ignore[type-arg]
    project, task = _get_task(project_id, task_id)
    if task.state != TaskState.FRAME_READY:
        raise HTTPException(400, f"Cannot submit mask in state {task.state}")

    raw_bytes = await file.read()
    try:
        result = save_mask(task, raw_bytes)
    except ValueError as e:
        raise HTTPException(400, str(e))

    # Auto-transition to READY if survey is complete.
    if project.config.survey_complete:
        task.transition(TaskState.READY)

    return result


# ── Config update ────────────────────────────────────────────────────── #


@router.post("/api/projects/{project_id}/tasks/{task_id}/job-spec")
async def update_job_spec(project_id: str, task_id: str, body: dict) -> dict[str, bool]:  # type: ignore[type-arg]
    """Update fields on the task's job spec."""
    project, task = _get_task(project_id, task_id)
    spec_dict = dict(task.config.job_spec)
    # Merge provided fields into the existing job spec
    for key in (
        "target_description", "capabilities", "evaluation", "goal_type",
        "input_mutation_hints", "max_tool_calls",
        "message_limit", "run_seconds", "hud_min_mean", "preserve_max_mean",
    ):
        if key in body:
            spec_dict[key] = body[key]
    # Validate
    from src.agent.job_spec import JobSpec

    spec = JobSpec.from_dict(spec_dict)
    errors = spec.validate()
    if errors:
        raise HTTPException(400, f"Invalid job spec: {'; '.join(errors)}")
    task.config.job_spec = spec.to_dict()
    # Preserve preset marker if it was set
    if "_preset" in task.config.job_spec:
        task.config.job_spec["_preset"] = task.config.job_spec["_preset"]
    task.save()
    return {"ok": True}


@router.post("/api/projects/{project_id}/tasks/{task_id}/config")
async def update_config(project_id: str, task_id: str, body: dict) -> dict[str, bool]:  # type: ignore[type-arg]
    """Legacy config update endpoint — maps to job spec fields."""
    project, task = _get_task(project_id, task_id)
    spec_dict = dict(task.config.job_spec) if task.config.job_spec else {}
    if "hint" in body:
        spec_dict["target_description"] = body["hint"]
    if "run_seconds" in body:
        spec_dict["run_seconds"] = body["run_seconds"]
    if "hud_min_mean" in body:
        spec_dict["hud_min_mean"] = body["hud_min_mean"]
    if "preserve_max_mean" in body:
        spec_dict["preserve_max_mean"] = body["preserve_max_mean"]
    if "prompt_fields" in body:
        # Noclip prompt fields -> target_description
        pf = body["prompt_fields"]
        if pf.get("objective"):
            spec_dict["target_description"] = pf["objective"]
    if spec_dict:
        from src.agent.job_spec import JobSpec

        spec = JobSpec.from_dict(spec_dict)
        task.config.job_spec = spec.to_dict()
    task.save()
    return {"ok": True}


# ── Agent run ────────────────────────────────────────────────────────── #


@router.post("/api/projects/{project_id}/tasks/{task_id}/run")
async def start_run(project_id: str, task_id: str, background_tasks: BackgroundTasks) -> dict[str, bool]:  # type: ignore[type-arg]
    project, task = _get_task(project_id, task_id)
    spec = task.config.get_job_spec()

    # Auto-transition to READY based on job spec requirements
    if task.state != TaskState.READY:
        if not spec.needs_savestate and not spec.needs_mask:
            # No runtime needed (e.g., research) — go straight to READY
            task.transition(TaskState.READY)
        elif spec.needs_savestate and not spec.needs_mask:
            # Runtime but no mask (e.g., position, noclip) — need savestate
            if not task.config.savestate_id:
                raise HTTPException(400, "This task requires a savestate")
            task.transition(TaskState.READY)
        # Visual tasks (needs_mask) must go through the full wizard

    if task.state != TaskState.READY:
        raise HTTPException(400, f"Cannot start run in state {task.state}")

    from src.agent.runner import run_agent

    async def _run() -> None:
        p, t = _get_task(project_id, task_id)
        await run_agent(t, p)

    background_tasks.add_task(_run)
    return {"ok": True}


# ── SSE event stream (task level) ────────────────────────────────────── #


@router.get("/api/projects/{project_id}/tasks/{task_id}/events")
async def task_event_stream(project_id: str, task_id: str) -> StreamingResponse:
    project, task = _get_task(project_id, task_id)
    return StreamingResponse(
        stream_events(task),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# ── Results ──────────────────────────────────────────────────────────── #


@router.get("/api/projects/{project_id}/tasks/{task_id}/result")
async def get_result(project_id: str, task_id: str) -> dict:  # type: ignore[type-arg]
    project, task = _get_task(project_id, task_id)
    if task.state not in (TaskState.DONE, TaskState.FAILED):
        raise HTTPException(400, f"No result yet (state: {task.state})")
    return {
        "verdict": task.config.result_verdict,
        "gecko": task.config.result_gecko,
        "hud_mean": task.config.result_hud_mean,
        "preserve_mean": task.config.result_preserve_mean,
        "has_frame": task.result_frame_path.exists(),
    }


@router.get("/api/projects/{project_id}/tasks/{task_id}/result.gecko")
async def download_gecko(project_id: str, task_id: str) -> FileResponse:
    project, task = _get_task(project_id, task_id)
    if not task.result_gecko_path.exists():
        raise HTTPException(404, "No gecko code found")
    game_id = project.config.game_id
    return FileResponse(
        task.result_gecko_path,
        media_type="text/plain",
        filename=f"{game_id}_hud_off.gecko",
    )


# ── Serve task files (reference, mask, result frame) ─────────────────── #


@router.get("/api/projects/{project_id}/tasks/{task_id}/files/{filename}")
async def get_task_file(project_id: str, task_id: str, filename: str) -> FileResponse:
    project, task = _get_task(project_id, task_id)
    allowed = {"reference.png", "mask.png", "result_frame.png", "config.json"}
    if filename not in allowed:
        raise HTTPException(403, f"File {filename} not serveable")
    path = task.root / filename
    if not path.exists():
        raise HTTPException(404, f"File {filename} not found")
    return FileResponse(path)
