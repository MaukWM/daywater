"""Findings tools — per-project and per-savestate discovery persistence.

Tools: save_finding, list_findings (project-scoped),
       save_savestate_finding, list_savestate_findings (savestate-scoped).
"""

from __future__ import annotations

from pathlib import Path

from inspect_ai.tool import Tool, tool

from src.knowledge import FindingKind, FindingsStore


# ── Project-scoped findings ──────────────────────────────────────────── #


@tool
def save_finding(project_root: Path, task_id: str = "") -> Tool:
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
            source_task=task_id,
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


# ── Savestate-scoped findings ───────────────────────────────────────── #


@tool
def save_savestate_finding(savestate_root: Path, task_id: str = "") -> Tool:
    """Build a savestate-scoped finding tool."""

    async def execute(
        kind: str,
        label: str,
        detail: str,
        address: str = "",
    ) -> str:
        """Save a runtime discovery to this savestate's findings.

        These findings are specific to this savestate's memory layout. Use this
        to record exact RAM addresses for player position, velocity, etc.

        Args:
            kind: "address" for memory addresses, "note" for observations.
            label: Short identifier (e.g. "player_x", "player_y", "player_z").
            detail: What this address holds and how you confirmed it.
            address: Hex address (e.g. "8030FA4C"). Required for "address" kind.
        """
        if kind not in ("address", "note"):
            return f"Error: kind must be 'address' or 'note', got '{kind}'"
        if kind == "address" and not address.strip():
            return "Error: address findings require an address."
        if not label.strip():
            return "Error: label is required."

        store = FindingsStore.load(savestate_root)
        finding = store.add(
            kind=kind,
            label=label.strip(),
            detail=detail.strip(),
            address=address.strip(),
            source_task=task_id,
        )
        addr_str = f" @ 0x{finding.address}" if finding.address else ""
        return f"Savestate finding {finding.id} saved: {finding.label}{addr_str}"

    return execute


@tool
def list_savestate_findings(savestate_root: Path) -> Tool:
    """Build a savestate-scoped findings list tool."""

    async def execute() -> str:
        """List all runtime findings saved for this savestate.

        Shows memory addresses and labels discovered during position testing.
        """
        store = FindingsStore.load(savestate_root)
        if not store.findings:
            return "No savestate findings yet."
        return store.format_table()

    return execute
