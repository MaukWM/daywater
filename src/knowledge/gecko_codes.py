"""Per-project Gecko code knowledge base.

Stores working Gecko codes with metadata so they can be retrieved by
future tasks or displayed in the web UI.

Storage layout::

    <project_root>/gecko_codes/
    ├── .gecko_meta.json      # {filename: {name, description, task_id, created_at}}
    ├── Remove_HUD_Overlay.gecko
    └── Noclip.gecko
"""

from __future__ import annotations

import json
from pathlib import Path


class GeckoCodeStore:
    """Persistent store for Gecko codes and their metadata."""

    def __init__(self, project_root: Path) -> None:
        self._dir = project_root / "gecko_codes"
        self._meta_path = self._dir / ".gecko_meta.json"

    @property
    def dir(self) -> Path:
        self._dir.mkdir(parents=True, exist_ok=True)
        return self._dir

    def load_meta(self) -> dict[str, dict[str, str | float]]:
        """Load gecko code metadata."""
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

    def list_codes(self) -> list[dict[str, str]]:
        """List all saved Gecko codes with metadata for the frontend."""
        if not self._dir.is_dir():
            return []

        meta = self.load_meta()
        codes = []
        for f in sorted(self._dir.glob("*.gecko")):
            entry = meta.get(f.name, {})
            text = f.read_text().strip()
            name = text.splitlines()[0].lstrip("$") if text else f.stem
            body_lines = [ln for ln in text.splitlines() if not ln.startswith("$")]
            codes.append({
                "filename": f.name,
                "name": name,
                "lines": str(len(body_lines)),
                "description": str(entry.get("description", "")),
                "task_id": str(entry.get("task_id", "")),
                "created_at": str(entry.get("created_at", "")),
            })
        return codes

    def read_code(self, filename: str) -> tuple[str, str]:
        """Read a gecko code file and its description. Returns (content, description)."""
        path = self._dir / filename
        if not path.exists() or not path.resolve().is_relative_to(self._dir.resolve()):
            raise FileNotFoundError(f"Gecko code {filename} not found")
        meta = self.load_meta()
        entry = meta.get(filename, {})
        return path.read_text(), str(entry.get("description", ""))

    def delete_code(self, filename: str) -> None:
        """Delete a gecko code and its metadata."""
        path = self._dir / filename
        if not path.exists() or not path.resolve().is_relative_to(self._dir.resolve()):
            raise FileNotFoundError(f"Gecko code {filename} not found")
        path.unlink()
        meta = self.load_meta()
        meta.pop(filename, None)
        self.save_meta(meta)
