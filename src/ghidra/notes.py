"""Mutable sidecar that lets the agent rename functions + leave notes.

Persisted at `<cache_dir>/notes.json`. Atomic write per mutation (temp +
rename) so a crash mid-mutation can't half-clobber the file. No locking —
one Inspect AI Sample runs at a time, single writer.

Shape (v2 — with source_task tracking):

    {
      "version": 2,
      "renames": {"80066548": {"value": "hud_render_loop", "task_id": "abc123"}},
      "notes":   {"80066548": {"value": "called from main loop", "task_id": "abc123"}}
    }

Backwards compat: v1 entries (bare strings) are auto-migrated on load.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

NOTES_VERSION = 2


@dataclass
class NotesStore:
    """In-memory view of `notes.json`, persisted on each mutation."""

    path: Path
    # {addr: {value, task_id}}
    renames: dict[str, dict[str, str]] = field(default_factory=dict)
    notes: dict[str, dict[str, str]] = field(default_factory=dict)

    @classmethod
    def load(cls, cache_dir: Path) -> NotesStore:
        path = cache_dir / "notes.json"
        if not path.exists():
            return cls(path=path)
        raw = json.loads(path.read_text() or "{}")

        # Migrate v1 (bare strings) to v2 (dicts with value + task_id)
        renames = _migrate_entries(raw.get("renames", {}))
        notes_data = _migrate_entries(raw.get("notes", {}))

        return cls(path=path, renames=renames, notes=notes_data)

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

    def rename(self, addr_hex: str, new_name: str, task_id: str = "") -> None:
        self.renames[addr_hex.lower()] = {"value": new_name, "task_id": task_id}
        self._flush()

    def add_note(self, addr_hex: str, text: str, task_id: str = "") -> None:
        self.notes[addr_hex.lower()] = {"value": text, "task_id": task_id}
        self._flush()

    def display_name(self, addr_hex: str, fallback: str) -> str:
        entry = self.renames.get(addr_hex.lower())
        if entry is None:
            return fallback
        return entry.get("value", fallback)

    def get_note(self, addr_hex: str) -> str:
        entry = self.notes.get(addr_hex.lower())
        if entry is None:
            return ""
        return entry.get("value", "")

    def remove_for_task(self, task_id: str) -> tuple[int, int]:
        """Remove all renames and notes created by a specific task.

        Returns (renames_removed, notes_removed).
        """
        r_removed = 0
        n_removed = 0
        for addr in list(self.renames):
            if self.renames[addr].get("task_id") == task_id:
                del self.renames[addr]
                r_removed += 1
        for addr in list(self.notes):
            if self.notes[addr].get("task_id") == task_id:
                del self.notes[addr]
                n_removed += 1
        if r_removed or n_removed:
            self._flush()
        return r_removed, n_removed

    # Flat access for backwards compat with code that reads renames/notes
    def renames_flat(self) -> dict[str, str]:
        """Return {addr: name} for display purposes."""
        return {addr: e.get("value", "") for addr, e in self.renames.items()}

    def notes_flat(self) -> dict[str, str]:
        """Return {addr: text} for display purposes."""
        return {addr: e.get("value", "") for addr, e in self.notes.items()}


def _migrate_entries(raw: dict[str, Any]) -> dict[str, dict[str, str]]:
    """Migrate v1 bare-string entries to v2 {value, task_id} dicts."""
    result: dict[str, dict[str, str]] = {}
    for addr, val in raw.items():
        addr = str(addr).lower()
        if isinstance(val, str):
            # v1 format: bare string
            result[addr] = {"value": val, "task_id": ""}
        elif isinstance(val, dict):
            # v2 format already
            result[addr] = {"value": str(val.get("value", "")), "task_id": str(val.get("task_id", ""))}
        else:
            result[addr] = {"value": str(val), "task_id": ""}
    return result
