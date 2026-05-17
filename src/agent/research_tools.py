"""Agent tools for per-project research documents.

Each doc has metadata (summary, source task, timestamp) stored in
.research_meta.json. The index is auto-generated from these summaries —
the agent never writes INDEX.md directly.

Storage layout::

    <project_root>/research/
    ├── .research_meta.json   # {filename: {summary, task_id, created_at}}
    ├── npc-behaviour.md      # agent-created research doc
    ├── shooting.md           # agent-created research doc
    └── ...
"""

from __future__ import annotations

import json
import time
from pathlib import Path

from inspect_ai.tool import Tool, tool


def _research_dir(project_root: Path) -> Path:
    d = project_root / "research"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _meta_path(research_dir: Path) -> Path:
    return research_dir / ".research_meta.json"


def _load_meta(research_dir: Path) -> dict[str, dict[str, str | float]]:
    """Load research doc metadata. Returns {filename: {summary, task_id, created_at}}."""
    path = _meta_path(research_dir)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, ValueError):
        return {}


def _save_meta(research_dir: Path, meta: dict[str, dict[str, str | float]]) -> None:
    _meta_path(research_dir).write_text(json.dumps(meta, indent=2))


def build_index(project_root: Path) -> str:
    """Build the research index from doc metadata. Used by agent + frontend."""
    rd = _research_dir(project_root)
    meta = _load_meta(rd)

    # Also pick up orphan docs (created before metadata tracking)
    on_disk = sorted(p.name for p in rd.glob("*.md") if p.name != "INDEX.md")

    if not on_disk and not meta:
        return "# Research Index\n\nNo research documents yet."

    lines = ["# Research Index\n"]
    for filename in on_disk:
        entry = meta.get(filename, {})
        summary = entry.get("summary", "(no summary)")
        lines.append(f"- **{filename}** — {summary}")

    return "\n".join(lines)


def list_docs(project_root: Path) -> list[dict[str, str]]:
    """Return structured doc list for the frontend."""
    rd = _research_dir(project_root)
    meta = _load_meta(rd)
    on_disk = sorted(p.name for p in rd.glob("*.md") if p.name != "INDEX.md")

    result = []
    for filename in on_disk:
        entry = meta.get(filename, {})
        result.append({
            "filename": filename,
            "summary": str(entry.get("summary", "")),
            "task_id": str(entry.get("task_id", "")),
            "created_at": float(entry.get("created_at", 0)),
        })
    return result


def get_research_docs_for_task(project_root: Path, task_id: str) -> list[str]:
    """Return filenames of research docs created by a specific task."""
    rd = _research_dir(project_root)
    meta = _load_meta(rd)
    return [fn for fn, entry in meta.items() if entry.get("task_id") == task_id]


def remove_research_docs_for_task(project_root: Path, task_id: str) -> list[str]:
    """Delete all research docs created by a specific task. Returns deleted filenames."""
    rd = _research_dir(project_root)
    meta = _load_meta(rd)

    deleted = []
    for fn in list(meta.keys()):
        if meta[fn].get("task_id") == task_id:
            doc_path = rd / fn
            if doc_path.exists():
                doc_path.unlink()
                deleted.append(fn)
            del meta[fn]

    _save_meta(rd, meta)
    return deleted


# ── Agent tools ──────────────────────────────────────────────────────── #


@tool
def list_research(project_root: Path) -> Tool:
    """Build the ``list_research`` tool bound to a project directory."""

    async def execute() -> str:
        """Read the research index for this game.

        Returns an auto-generated index of all research documents with
        their summaries. Always check this at the start of a run to see
        what prior tasks have already documented.
        """
        return build_index(project_root)

    return execute


@tool
def read_research(project_root: Path) -> Tool:
    """Build the ``read_research`` tool bound to a project directory."""

    async def execute(filename: str) -> str:
        """Read a research document.

        Args:
            filename: Name of the document (e.g. "npc-behaviour.md").
                Must end in .md.
        """
        if not filename.endswith(".md"):
            filename += ".md"

        rd = _research_dir(project_root)
        path = rd / filename

        if not path.exists():
            available = sorted(p.name for p in rd.glob("*.md") if p.name != "INDEX.md")
            return f"Document '{filename}' not found. Available: {', '.join(available) or 'none'}"

        # Prevent path traversal
        if not path.resolve().is_relative_to(rd.resolve()):
            return "Error: invalid filename."

        return path.read_text()

    return execute


@tool
def write_research(project_root: Path, task_id: str = "") -> Tool:
    """Build the ``write_research`` tool bound to a project directory."""

    async def execute(filename: str, content: str, summary: str = "") -> str:
        """Write or update a research document.

        Use this to document your findings about game systems, code
        structure, function purposes, and anything that would help
        future tasks understand this game. Write like a researcher
        documenting discoveries — include addresses, function names,
        your reasoning, and what you confirmed vs what's hypothetical.

        The index is auto-generated from document summaries, so you
        do NOT need to write INDEX.md. Just provide a good summary.

        Args:
            filename: Name for the document (e.g. "npc-behaviour.md",
                "shooting-mechanics.md"). Must end in .md. Cannot be
                "INDEX.md" (the index is auto-generated).
            content: Full markdown content for the document.
            summary: One-line summary of what this document covers.
                This appears in the research index shown to future tasks.
                Keep it concise and informative.
        """
        if not filename.endswith(".md"):
            filename += ".md"

        if filename.lower() == "index.md":
            return (
                "Error: INDEX.md is auto-generated from document summaries. "
                "Write your research to a named document instead (e.g. "
                "'player-movement.md') and provide a summary."
            )

        rd = _research_dir(project_root)
        path = rd / filename

        # Prevent path traversal
        if not path.resolve().is_relative_to(rd.resolve()):
            return "Error: invalid filename."

        if not content.strip():
            return "Error: content is empty."

        path.write_text(content)

        # Update metadata
        meta = _load_meta(rd)
        existing = meta.get(filename, {})
        meta[filename] = {
            "summary": summary.strip() or str(existing.get("summary", "")),
            "task_id": task_id or str(existing.get("task_id", "")),
            "created_at": float(existing.get("created_at", 0)) or time.time(),
        }
        _save_meta(rd, meta)

        return f"Written: research/{filename} ({len(content)} bytes). Summary: {summary or '(unchanged)'}"

    return execute
