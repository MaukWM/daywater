"""Project-level GameCube controller mapping.

Stores human descriptions of what each button/stick does in a specific game.
Persisted at ``<project_root>/controller_mapping.json``.

Schema::

    {
      "buttons": {
        "A": "Jump",
        "B": "Crouch / interact",
        "X": "",
        ...
      },
      "sticks": {
        "MAIN": {
          "description": "Player movement",
          "up": "Walk forward",
          "down": "Walk backward",
          "left": "Strafe left",
          "right": "Strafe right"
        },
        "C": {
          "description": "Camera / look",
          "up": "Look up",
          "down": "Look down",
          "left": "Look left",
          "right": "Look right"
        }
      }
    }
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

# All GC buttons in display order.
GC_BUTTONS = ["A", "B", "X", "Y", "Z", "L", "R", "START", "D_UP", "D_DOWN", "D_LEFT", "D_RIGHT"]

# Sticks with sub-directions.
GC_STICKS = ["MAIN", "C"]
STICK_DIRS = ["up", "down", "left", "right"]

_FILENAME = "controller_mapping.json"


def _empty_mapping() -> dict[str, Any]:
    """Return a blank mapping with all buttons and sticks."""
    return {
        "buttons": {b: "" for b in GC_BUTTONS},
        "sticks": {
            s: {"description": "", "up": "", "down": "", "left": "", "right": ""}
            for s in GC_STICKS
        },
    }


def load_mapping(project_root: Path) -> dict[str, Any]:
    """Load the controller mapping for a project, or return an empty one."""
    path = project_root / _FILENAME
    if not path.exists():
        return _empty_mapping()
    try:
        data = json.loads(path.read_text())
        # Ensure all keys exist (forward compat if we add buttons later)
        mapping = _empty_mapping()
        for b in GC_BUTTONS:
            if b in data.get("buttons", {}):
                mapping["buttons"][b] = data["buttons"][b]
        for s in GC_STICKS:
            if s in data.get("sticks", {}):
                stick_data = data["sticks"][s]
                mapping["sticks"][s]["description"] = stick_data.get("description", "")
                for d in STICK_DIRS:
                    mapping["sticks"][s][d] = stick_data.get(d, "")
        return mapping
    except (json.JSONDecodeError, TypeError):
        return _empty_mapping()


def save_mapping(project_root: Path, mapping: dict[str, Any]) -> None:
    """Persist the controller mapping."""
    path = project_root / _FILENAME
    path.write_text(json.dumps(mapping, indent=2))


def format_mapping_for_prompt(mapping: dict[str, Any]) -> str:
    """Format the controller mapping as text for injection into agent prompts."""
    lines: list[str] = []

    # Sticks first (most important for movement)
    for stick_name in GC_STICKS:
        stick = mapping.get("sticks", {}).get(stick_name, {})
        desc = stick.get("description", "")
        has_dirs = any(stick.get(d) for d in STICK_DIRS)
        if desc or has_dirs:
            label = "Main stick" if stick_name == "MAIN" else "C-stick"
            if desc:
                lines.append(f"- {label}: {desc}")
            for d in STICK_DIRS:
                if stick.get(d):
                    lines.append(f"  - {d}: {stick[d]}")

    # Buttons
    for btn in GC_BUTTONS:
        desc = mapping.get("buttons", {}).get(btn, "")
        if desc:
            lines.append(f"- {btn} button: {desc}")

    if not lines:
        return "No controller mapping configured for this game."

    return "Controller mapping:\n" + "\n".join(lines)
