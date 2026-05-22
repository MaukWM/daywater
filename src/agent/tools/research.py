"""Agent tools for per-project research documents.

The storage layer lives in ``src.knowledge.research.ResearchStore``.
This module provides the Inspect AI ``@tool`` wrappers that give the
agent access to read, write, and list research docs.
"""

from __future__ import annotations

import time
from pathlib import Path

from inspect_ai.tool import Tool, tool

from src.knowledge.research import ResearchStore


def build_index(project_root: Path) -> str:
    """Build the research index. Convenience wrapper for external callers."""
    return ResearchStore(project_root).build_index()


def list_docs(project_root: Path) -> list[dict[str, str]]:
    """Return structured doc list. Convenience wrapper for external callers."""
    return ResearchStore(project_root).list_docs()


def get_research_docs_for_task(project_root: Path, task_id: str) -> list[str]:
    """Return filenames of research docs created by a specific task."""
    return ResearchStore(project_root).docs_for_task(task_id)


def remove_research_docs_for_task(project_root: Path, task_id: str) -> list[str]:
    """Delete all research docs created by a specific task."""
    return ResearchStore(project_root).remove_docs_for_task(task_id)


# ── Agent tools ──────────────────────────────────────────────────────── #


@tool
def list_research(project_root: Path) -> Tool:
    """Build the ``list_research`` tool bound to a project directory."""

    _store = ResearchStore(project_root)

    async def execute() -> str:
        """Read the research index for this game.

        Returns an auto-generated index of all research documents with
        their summaries. Always check this at the start of a run to see
        what prior tasks have already documented.
        """
        return _store.build_index()

    return execute


@tool
def read_research(project_root: Path) -> Tool:
    """Build the ``read_research`` tool bound to a project directory."""

    _store = ResearchStore(project_root)

    async def execute(filename: str) -> str:
        """Read a research document.

        Args:
            filename: Name of the document (e.g. "npc-behaviour.md").
                Must end in .md.
        """
        if not filename.endswith(".md"):
            filename += ".md"

        path = _store.dir / filename

        if not path.exists():
            available = sorted(p.name for p in _store.dir.glob("*.md") if p.name != "INDEX.md")
            return f"Document '{filename}' not found. Available: {', '.join(available) or 'none'}"

        # Prevent path traversal
        if not path.resolve().is_relative_to(_store.dir.resolve()):
            return "Error: invalid filename."

        return path.read_text()

    return execute


@tool
def write_research(project_root: Path, task_id: str = "") -> Tool:
    """Build the ``write_research`` tool bound to a project directory."""

    _store = ResearchStore(project_root)

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

        path = _store.dir / filename

        # Prevent path traversal
        if not path.resolve().is_relative_to(_store.dir.resolve()):
            return "Error: invalid filename."

        if not content.strip():
            return "Error: content is empty."

        path.write_text(content)

        # Update metadata
        meta = _store.load_meta()
        existing = meta.get(filename, {})
        meta[filename] = {
            "summary": summary.strip() or str(existing.get("summary", "")),
            "task_id": task_id or str(existing.get("task_id", "")),
            "created_at": float(existing.get("created_at", 0)) or time.time(),
        }
        _store.save_meta(meta)

        return f"Written: research/{filename} ({len(content)} bytes). Summary: {summary or '(unchanged)'}"

    return execute
