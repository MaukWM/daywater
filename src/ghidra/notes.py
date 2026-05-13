"""Mutable sidecar that lets the agent rename functions + leave notes.

Persisted at `<cache_dir>/notes.json`. Atomic write per mutation (temp +
rename) so a crash mid-mutation can't half-clobber the file. No locking —
one Inspect AI Sample runs at a time, single writer.

Shape:

    {
      "version": 1,
      "renames": {"80066548": "hud_render_loop"},
      "notes":   {"80066548": "called from main game loop, iterates HUD entries"}
    }
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

NOTES_VERSION = 1


@dataclass
class NotesStore:
    """In-memory view of `notes.json`, persisted on each mutation."""

    path: Path
    renames: dict[str, str] = field(default_factory=dict)
    notes: dict[str, str] = field(default_factory=dict)

    @classmethod
    def load(cls, cache_dir: Path) -> NotesStore:
        path = cache_dir / "notes.json"
        if not path.exists():
            return cls(path=path)
        raw = json.loads(path.read_text() or "{}")
        return cls(
            path=path,
            renames={str(k).lower(): str(v) for k, v in raw.get("renames", {}).items()},
            notes={str(k).lower(): str(v) for k, v in raw.get("notes", {}).items()},
        )

    def _flush(self) -> None:
        payload = json.dumps(
            {"version": NOTES_VERSION, "renames": self.renames, "notes": self.notes},
            indent=2,
            sort_keys=True,
        )
        tmp = tempfile.NamedTemporaryFile(
            "w",
            dir=str(self.path.parent),
            delete=False,
            prefix=".notes-",
            suffix=".tmp",
        )
        try:
            tmp.write(payload)
            tmp.flush()
            os.fsync(tmp.fileno())
        finally:
            tmp.close()
        os.replace(tmp.name, self.path)

    def rename(self, addr_hex: str, new_name: str) -> None:
        self.renames[addr_hex.lower()] = new_name
        self._flush()

    def add_note(self, addr_hex: str, text: str) -> None:
        self.notes[addr_hex.lower()] = text
        self._flush()

    def display_name(self, addr_hex: str, fallback: str) -> str:
        return self.renames.get(addr_hex.lower(), fallback)
