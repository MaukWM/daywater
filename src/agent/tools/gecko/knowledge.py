"""Gecko code knowledge base — save, list, and read gecko codes.

Tools: save_gecko_code, save_noclip_code, list_gecko_codes, read_gecko_code.
Shared by both live and visual gecko paths.
"""

from __future__ import annotations

from pathlib import Path

from inspect_ai.tool import Tool, tool

from src.logging import logger


@tool
def save_gecko_code(task_root: Path, project_root: Path | None = None) -> Tool:
    """Build a tool that saves the final working Gecko code."""

    async def execute(gecko_text: str, description: str = "") -> str:
        """Save the final working Gecko code.

        Call this after you've confirmed the code works. The code is saved
        to both the current task and the project knowledge base so future
        tasks can retrieve it with list_gecko_codes / read_gecko_code.

        Args:
            gecko_text: The complete Gecko code text (with $Name headers).
            description: A brief explanation of what this code does, how it
                works, and any caveats. Shown in the knowledge base UI and
                to future tasks. Include: what it patches, how to use it,
                and what controls/inputs are relevant.
        """
        import json
        import time as _time

        from src.dolphin.gecko import parse_gecko

        codes = parse_gecko(gecko_text)
        if not codes:
            return "Error: no valid Gecko codes found."

        # Save to task directory
        code_path = task_root / "gecko_code.txt"
        code_path.write_text(gecko_text)

        # Also save to project-level gecko_codes/ for cross-task access
        parts = [f"Saved {len(codes)} Gecko code(s) to task."]
        if project_root is not None:
            gecko_dir = project_root / "gecko_codes"
            gecko_dir.mkdir(exist_ok=True)

            # Load/update metadata
            meta_path = gecko_dir / ".gecko_meta.json"
            meta: dict[str, dict[str, str | float]] = {}
            if meta_path.exists():
                meta = json.loads(meta_path.read_text())

            for code in codes:
                name_safe = code.name.replace("/", "_").replace(" ", "_")
                filename = f"{name_safe}.gecko"
                dest = gecko_dir / filename
                block = f"${code.name}\n" + "\n".join(code.lines) + "\n"
                dest.write_text(block)

                meta[filename] = {
                    "name": code.name,
                    "description": description.strip(),
                    "task_id": str(task_root.name),
                    "created_at": _time.time(),
                }

            meta_path.write_text(json.dumps(meta, indent=2))
            names = ", ".join(c.name for c in codes)
            parts.append(f"Also saved to project knowledge base: {names}")

        logger.info("gecko_code_saved", path=str(code_path), codes=len(codes))
        return " ".join(parts)

    return execute


# Backwards compat alias
save_noclip_code = save_gecko_code


@tool
def list_gecko_codes(project_root: Path) -> Tool:
    """Build the list_gecko_codes tool bound to a project directory."""

    async def execute() -> str:
        """List all saved Gecko codes in the project knowledge base.

        Shows codes saved by previous tasks via save_gecko_code, including
        their descriptions. Use read_gecko_code(name) to retrieve the full
        code text.
        """
        import json

        gecko_dir = project_root / "gecko_codes"
        if not gecko_dir.is_dir():
            return "No saved Gecko codes yet."

        files = sorted(gecko_dir.glob("*.gecko"))
        if not files:
            return "No saved Gecko codes yet."

        # Load metadata for descriptions
        meta_path = gecko_dir / ".gecko_meta.json"
        meta: dict[str, dict[str, str]] = {}
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())

        lines = ["Saved Gecko codes:"]
        for f in files:
            text = f.read_text().strip()
            body_lines = [l for l in text.splitlines() if not l.startswith("$")]
            entry = meta.get(f.name, {})
            desc = entry.get("description", "")
            if len(desc) > 120:
                desc = desc[:117] + "..."
            desc_part = f" — {desc}" if desc else ""
            lines.append(f"  - {f.stem} ({len(body_lines)} lines){desc_part}")
        return "\n".join(lines)

    return execute


@tool
def read_gecko_code(project_root: Path) -> Tool:
    """Build the read_gecko_code tool bound to a project directory."""

    async def execute(name: str) -> str:
        """Read a saved Gecko code from the project knowledge base.

        Args:
            name: The code name (as shown by list_gecko_codes). Do not
                  include the .gecko extension.

        Returns:
            The full Gecko code text with description. The code text is
            ready to pass directly to apply_gecko_code.
        """
        import json

        gecko_dir = project_root / "gecko_codes"
        # Try exact match, then with .gecko extension
        candidates = [
            gecko_dir / f"{name}.gecko",
            gecko_dir / name,
        ]
        for p in candidates:
            if p.is_file():
                code_text = p.read_text()
                # Load description from metadata
                meta_path = gecko_dir / ".gecko_meta.json"
                desc = ""
                if meta_path.exists():
                    meta = json.loads(meta_path.read_text())
                    entry = meta.get(p.name, {})
                    desc = entry.get("description", "")

                parts = []
                if desc:
                    parts.append(f"Description: {desc}")
                    parts.append("")
                parts.append(code_text.strip())
                return "\n".join(parts)

        # Fuzzy: list available
        if gecko_dir.is_dir():
            available = [f.stem for f in gecko_dir.glob("*.gecko")]
            return f"Not found: '{name}'. Available: {', '.join(available) or '(none)'}"
        return f"Not found: '{name}'. No gecko codes directory exists yet."

    return execute
