"""Knowledge base routes: findings, research docs, gecko codes, unified knowledge."""

from __future__ import annotations

import shutil
from dataclasses import asdict

from fastapi import APIRouter, HTTPException

from src.core.ghidra.notes import NotesStore
from src.core.knowledge import FindingsStore, GeckoCodeStore, ResearchStore
from src.core.paths import binaries_cache
from src.web.api.deps import _get_project

router = APIRouter()


# ── Findings ─────────────────────────────────────────────────────────── #


@router.get("/api/projects/{project_id}/findings")
async def get_findings(project_id: str) -> list[dict]:  # type: ignore[type-arg]
    project = _get_project(project_id)
    fs = FindingsStore.load(project.root)
    return [asdict(f) for f in fs.list_all()]


@router.delete("/api/projects/{project_id}/findings/{finding_id}")
async def delete_finding(project_id: str, finding_id: str) -> dict[str, bool]:
    project = _get_project(project_id)
    fs = FindingsStore.load(project.root)
    if not fs.remove(finding_id):
        raise HTTPException(404, f"Finding {finding_id} not found")
    return {"ok": True}


@router.delete("/api/projects/{project_id}/knowledge")
async def reset_knowledge(project_id: str) -> dict[str, bool]:
    """Clear all findings, research docs, and Ghidra renames/notes."""
    project = _get_project(project_id)

    # Clear findings
    fs = FindingsStore.load(project.root)
    fs.findings.clear()
    fs._flush()

    # Clear research docs
    research_dir = project.root / "research"
    if research_dir.exists():
        shutil.rmtree(research_dir, ignore_errors=True)

    # Clear Ghidra notes/renames from all cached binaries
    cache_root = binaries_cache()
    if cache_root.exists():
        for sha_dir in cache_root.iterdir():
            notes_path = sha_dir / "notes.json"
            if notes_path.exists():
                ns = NotesStore.load(sha_dir)
                if ns.renames or ns.notes:
                    ns.renames.clear()
                    ns.notes.clear()
                    ns._flush()

    return {"ok": True}


# ── Research docs ────────────────────────────────────────────────────── #


@router.get("/api/projects/{project_id}/research")
async def get_research_index(project_id: str) -> dict:  # type: ignore[type-arg]
    """Return the research index + list of available docs with summaries."""
    project = _get_project(project_id)
    store = ResearchStore(project.root)
    return {"index": store.build_index(), "docs": store.list_docs()}


@router.get("/api/projects/{project_id}/research/{filename}")
async def get_research_doc(project_id: str, filename: str) -> dict:  # type: ignore[type-arg]
    """Return a single research document."""
    project = _get_project(project_id)
    store = ResearchStore(project.root)
    path = store.dir / filename
    if not path.exists() or not path.resolve().is_relative_to(store.dir.resolve()):
        raise HTTPException(404, f"Document {filename} not found")
    return {"filename": filename, "content": path.read_text()}


@router.delete("/api/projects/{project_id}/research/{filename}")
async def delete_research_doc(project_id: str, filename: str) -> dict[str, bool]:
    """Delete a single research document and its metadata."""
    project = _get_project(project_id)
    store = ResearchStore(project.root)
    path = store.dir / filename
    if not path.exists() or not path.resolve().is_relative_to(store.dir.resolve()):
        raise HTTPException(404, f"Document {filename} not found")
    if filename == "INDEX.md":
        raise HTTPException(400, "INDEX.md is auto-generated and cannot be deleted directly")
    path.unlink()

    meta = store.load_meta()
    meta.pop(filename, None)
    store.save_meta(meta)

    return {"ok": True}


# ── Gecko codes knowledge base ─────────────────────────────────────── #


@router.get("/api/projects/{project_id}/gecko-codes")
async def get_gecko_codes(project_id: str) -> dict:  # type: ignore[type-arg]
    """List all saved Gecko codes with metadata."""
    project = _get_project(project_id)
    store = GeckoCodeStore(project.root)
    return {"codes": store.list_codes()}


@router.get("/api/projects/{project_id}/gecko-codes/{filename}")
async def get_gecko_code(project_id: str, filename: str) -> dict:  # type: ignore[type-arg]
    """Return a single Gecko code file."""
    project = _get_project(project_id)
    store = GeckoCodeStore(project.root)
    try:
        content, description = store.read_code(filename)
    except FileNotFoundError:
        raise HTTPException(404, f"Gecko code {filename} not found")
    return {"filename": filename, "content": content, "description": description}


@router.delete("/api/projects/{project_id}/gecko-codes/{filename}")
async def delete_gecko_code(project_id: str, filename: str) -> dict[str, bool]:
    """Delete a saved Gecko code."""
    project = _get_project(project_id)
    store = GeckoCodeStore(project.root)
    try:
        store.delete_code(filename)
    except FileNotFoundError:
        raise HTTPException(404, f"Gecko code {filename} not found")
    return {"ok": True}


# ── Unified knowledge ────────────────────────────────────────────────── #


@router.get("/api/projects/{project_id}/knowledge")
async def get_knowledge(project_id: str) -> dict:  # type: ignore[type-arg]
    """Combined knowledge base: findings + all Ghidra renames/notes across cached binaries."""
    project = _get_project(project_id)

    # Findings
    fs = FindingsStore.load(project.root)
    findings = [asdict(f) for f in fs.list_all()]

    # Ghidra notes/renames from all analyzed binaries
    cache_root = binaries_cache()

    renames: list[dict[str, str]] = []
    notes: list[dict[str, str]] = []

    if cache_root.exists():
        for sha_dir in sorted(cache_root.iterdir()):
            notes_path = sha_dir / "notes.json"
            if not notes_path.exists():
                continue
            ns = NotesStore.load(sha_dir)
            sha1 = sha_dir.name
            for addr, entry in ns.renames.items():
                renames.append({
                    "address": addr,
                    "name": entry.get("value", ""),
                    "binary": sha1[:8],
                    "task_id": entry.get("task_id", ""),
                })
            for addr, entry in ns.notes.items():
                notes.append({
                    "address": addr,
                    "text": entry.get("value", ""),
                    "binary": sha1[:8],
                    "task_id": entry.get("task_id", ""),
                })

    return {"findings": findings, "renames": renames, "notes": notes}
