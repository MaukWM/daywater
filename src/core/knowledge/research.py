"""Per-project research document store.

Each doc has metadata (summary, source task, timestamp) stored in
``.research_meta.json``. The index is auto-generated from these
summaries — the agent never writes ``INDEX.md`` directly.

Storage layout::

    <project_root>/research/
    ├── .research_meta.json   # {filename: {summary, task_id, created_at}}
    ├── npc-behaviour.md      # agent-created research doc
    └── INDEX.md              # auto-generated (never written by agent)
"""

from __future__ import annotations

import json
from pathlib import Path


class ResearchStore:
    """Persistent store for research documents and their metadata."""

    def __init__(self, project_root: Path) -> None:
        self._dir = project_root / "research"
        self._meta_path = self._dir / ".research_meta.json"

    @property
    def dir(self) -> Path:
        self._dir.mkdir(parents=True, exist_ok=True)
        return self._dir

    def load_meta(self) -> dict[str, dict[str, str | float]]:
        """Load research doc metadata. Returns {filename: {summary, task_id, created_at}}."""
        if not self._meta_path.exists():
            return {}
        try:
            return json.loads(self._meta_path.read_text())
        except (json.JSONDecodeError, ValueError):
            return {}

    def save_meta(self, meta: dict[str, dict[str, str | float]]) -> None:
        """Write metadata to disk."""
        self.dir  # ensure dir exists
        self._meta_path.write_text(json.dumps(meta, indent=2))

    def build_index(self) -> str:
        """Build the research index from doc metadata."""
        meta = self.load_meta()
        on_disk = sorted(p.name for p in self.dir.glob("*.md") if p.name != "INDEX.md")

        if not on_disk and not meta:
            return "# Research Index\n\nNo research documents yet."

        lines = ["# Research Index\n"]
        for filename in on_disk:
            entry = meta.get(filename, {})
            summary = entry.get("summary", "(no summary)")
            lines.append(f"- **{filename}** — {summary}")

        return "\n".join(lines)

    def list_docs(self) -> list[dict[str, str]]:
        """Return structured doc list for the frontend."""
        meta = self.load_meta()
        on_disk = sorted(p.name for p in self.dir.glob("*.md") if p.name != "INDEX.md")

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

    def docs_for_task(self, task_id: str) -> list[str]:
        """Return filenames of research docs created by a specific task."""
        meta = self.load_meta()
        return [fn for fn, entry in meta.items() if entry.get("task_id") == task_id]

    def remove_docs_for_task(self, task_id: str) -> list[str]:
        """Delete all research docs created by a specific task. Returns deleted filenames."""
        meta = self.load_meta()

        deleted = []
        for fn in list(meta.keys()):
            if meta[fn].get("task_id") == task_id:
                doc_path = self.dir / fn
                if doc_path.exists():
                    doc_path.unlink()
                    deleted.append(fn)
                del meta[fn]

        self.save_meta(meta)
        return deleted
