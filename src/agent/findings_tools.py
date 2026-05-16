"""Agent tools for the per-project findings store.

Closure-captured ``project_root`` so the tools know where to persist.
"""

from __future__ import annotations

from pathlib import Path

from inspect_ai.tool import Tool, tool

from src.findings import FindingsStore


@tool
def save_finding(project_root: Path) -> Tool:
    """Build the ``save_finding`` tool bound to a project directory."""

    async def execute(
        kind: str,
        label: str,
        detail: str,
        address: str = "",
    ) -> str:
        """Save a discovery about this game to the project knowledge base.

        Findings persist across tasks within the same project. Use this to
        record memory addresses, function purposes, or general observations
        that future tasks should know about.

        If the same address is saved again, the existing entry is updated.

        Args:
            kind: Type of finding. One of "address" (memory address, e.g.
                player position), "function" (function purpose), or "note"
                (general observation, no address needed).
            label: Short identifier (e.g. "player_x_pos", "collision_check").
            detail: Explanation of what you found and why it matters.
            address: Hex address (e.g. "8030FA4C" or "0x8030FA4C"). Required
                for "address" and "function" kinds. Omit for "note" kind.
        """
        if kind not in ("address", "function", "note"):
            return f"Error: kind must be 'address', 'function', or 'note', got '{kind}'"
        if kind in ("address", "function") and not address.strip():
            return f"Error: {kind} findings require an address."
        if not label.strip():
            return "Error: label is required."

        store = FindingsStore.load(project_root)
        finding = store.add(
            kind=kind,
            label=label.strip(),
            detail=detail.strip(),
            address=address.strip(),
        )
        addr_str = f" @ 0x{finding.address}" if finding.address else ""
        return f"Finding {finding.id} saved: {finding.label}{addr_str}"

    return execute


@tool
def list_findings(project_root: Path) -> Tool:
    """Build the ``list_findings`` tool bound to a project directory."""

    async def execute() -> str:
        """List all discoveries saved for this game across all tasks.

        Returns a table of findings including addresses, labels, and details.
        Check this at the start of a run to see what prior tasks discovered.
        """
        store = FindingsStore.load(project_root)
        return store.format_table()

    return execute
