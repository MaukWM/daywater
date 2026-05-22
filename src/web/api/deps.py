"""Shared dependencies used by multiple API routers."""

from __future__ import annotations

from fastapi import HTTPException

from src.paths import sessions_root
from src.web.sessions import Project, ProjectStore, Savestate, Task

store = ProjectStore(sessions_root())


def _get_project(project_id: str) -> Project:
    project = store.get(project_id)
    if project is None:
        raise HTTPException(404, f"Project {project_id} not found")
    return project


def _get_task(project_id: str, task_id: str) -> tuple[Project, Task]:
    project = _get_project(project_id)
    task = project.get_task(task_id)
    if task is None:
        raise HTTPException(404, f"Task {task_id} not found in project {project_id}")
    return project, task


def _get_savestate(project_id: str, savestate_id: str) -> tuple[Project, Savestate]:
    project = _get_project(project_id)
    ss = project.get_savestate(savestate_id)
    if ss is None:
        raise HTTPException(404, f"Savestate {savestate_id} not found")
    return project, ss
