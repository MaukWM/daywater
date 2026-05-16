"""Agent tools for per-project research documents.

Gives the agent a research journal scoped to the project directory.
The agent can create, read, and update free-form markdown documents
and maintains its own INDEX.md as a table of contents.

Storage layout::

    <project_root>/research/
    ├── INDEX.md          # table of contents (always shown to agent)
    ├── npc-behaviour.md  # agent-created research doc
    ├── shooting.md       # agent-created research doc
    └── ...
"""

from __future__ import annotations

from pathlib import Path

from inspect_ai.tool import Tool, tool


def _research_dir(project_root: Path) -> Path:
    d = project_root / "research"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ensure_index(research_dir: Path) -> Path:
    index = research_dir / "INDEX.md"
    if not index.exists():
        index.write_text("# Research Index\n\nNo research yet.\n")
    return index


@tool
def list_research(project_root: Path) -> Tool:
    """Build the ``list_research`` tool bound to a project directory."""

    async def execute() -> str:
        """Read the research index for this game.

        Returns the contents of INDEX.md, which is the table of contents
        for all research documents. Always check this at the start of a
        run to see what prior tasks have already documented.
        """
        rd = _research_dir(project_root)
        index = _ensure_index(rd)
        content = index.read_text()

        # Also list files so agent knows what's available
        docs = sorted(p.name for p in rd.glob("*.md") if p.name != "INDEX.md")
        if docs:
            content += "\n\n## Available documents\n\n"
            content += "\n".join(f"- {name}" for name in docs)

        return content

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
            available = sorted(p.name for p in rd.glob("*.md"))
            return f"Document '{filename}' not found. Available: {', '.join(available) or 'none'}"

        # Prevent path traversal
        if not path.resolve().is_relative_to(rd.resolve()):
            return "Error: invalid filename."

        return path.read_text()

    return execute


@tool
def write_research(project_root: Path) -> Tool:
    """Build the ``write_research`` tool bound to a project directory."""

    async def execute(filename: str, content: str) -> str:
        """Write or update a research document and update the index.

        Use this to document your findings about game systems, code
        structure, function purposes, and anything that would help
        future tasks understand this game. Write like a researcher
        documenting discoveries — include addresses, function names,
        your reasoning, and what you confirmed vs what's hypothetical.

        The INDEX.md is yours to manage. After writing a new doc,
        update the index by writing to "INDEX.md" with an updated
        table of contents.

        Args:
            filename: Name for the document (e.g. "npc-behaviour.md",
                "shooting-mechanics.md", "INDEX.md"). Must end in .md.
            content: Full markdown content for the document.
        """
        if not filename.endswith(".md"):
            filename += ".md"

        rd = _research_dir(project_root)
        path = rd / filename

        # Prevent path traversal
        if not path.resolve().is_relative_to(rd.resolve()):
            return "Error: invalid filename."

        if not content.strip():
            return "Error: content is empty."

        _ensure_index(rd)
        path.write_text(content)

        return f"Written: research/{filename} ({len(content)} bytes)"

    return execute
