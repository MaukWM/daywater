"""Memory reading and scanning tools for runtime Dolphin interaction.

Tools: read_memory, read_memory_batch, scan_memory, scan_memory_diff, find_writers.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from inspect_ai.tool import Tool, tool

from src.core.dolphin.memory import scan_floats_in_range

if TYPE_CHECKING:
    from src.core.dolphin.session import DolphinSession


# ── Memory reading tools ──────────────────────────────────────────────── #


@tool
def read_memory(session: DolphinSession) -> Tool:
    """Build a memory read tool bound to a DolphinSession."""

    async def execute(address: str, format: str = "f32") -> str:
        """Read a value from GameCube memory at a hex address.

        Args:
            address: Hex address, e.g. "0x8030FA4C" or "8030FA4C".
            format: Data type to read. One of "f32" (big-endian float),
                "u32" (big-endian unsigned 32-bit int), "u8" (single byte).
        """
        try:
            gc_addr = int(address, 16)
        except ValueError:
            return f"Error: invalid hex address '{address}'"

        try:
            if format == "f32":
                val = session.read_float(gc_addr)
                return f"0x{gc_addr:08X} = {val:.6f} (f32)"
            elif format == "u32":
                val = session.read_u32(gc_addr)
                return f"0x{gc_addr:08X} = {val} (0x{val:08X}) (u32)"
            elif format == "u8":
                raw = session.read_bytes(gc_addr, 1)
                return f"0x{gc_addr:08X} = {raw[0]} (0x{raw[0]:02X}) (u8)"
            else:
                return f"Error: unknown format '{format}'. Use 'f32', 'u32', or 'u8'."
        except Exception as e:
            return f"Error reading 0x{gc_addr:08X}: {e}"

    return execute


@tool
def read_memory_batch(session: DolphinSession) -> Tool:
    """Build a batch memory read tool bound to a DolphinSession."""

    async def execute(addresses: str, format: str = "f32") -> str:
        """Read multiple GameCube memory addresses at once.

        Args:
            addresses: Comma-separated hex addresses, e.g.
                "0x8030FA4C, 0x8030FA50, 0x8030FA54".
            format: Data type — "f32" or "u32". Applied to all addresses.
        """
        addr_strs = [a.strip() for a in addresses.split(",") if a.strip()]
        if not addr_strs:
            return "Error: no addresses provided."
        if len(addr_strs) > 50:
            return "Error: max 50 addresses per batch."

        lines = []
        for addr_str in addr_strs:
            try:
                gc_addr = int(addr_str, 16)
            except ValueError:
                lines.append(f"  {addr_str}: invalid hex")
                continue
            try:
                if format == "f32":
                    val = session.read_float(gc_addr)
                    lines.append(f"  0x{gc_addr:08X} = {val:.6f}")
                else:
                    val = session.read_u32(gc_addr)
                    lines.append(f"  0x{gc_addr:08X} = {val} (0x{val:08X})")
            except Exception as e:
                lines.append(f"  0x{gc_addr:08X}: error — {e}")

        return f"Read {len(addr_strs)} addresses ({format}):\n" + "\n".join(lines)

    return execute


# ── Memory scanning tool ──────────────────────────────────────────────── #


@tool
def scan_memory(session: DolphinSession) -> Tool:
    """Build a memory scanning tool bound to a DolphinSession."""

    async def execute(
        start: str = "0x80000000",
        end: str = "0x81800000",
        min_abs: float = 0.1,
        max_abs: float = 50000.0,
    ) -> str:
        """Scan GameCube memory for plausible float values (position candidates).

        Scans the given address range for 4-byte-aligned big-endian floats
        that are finite, nonzero, and within the absolute value bounds.
        This is useful for finding position, velocity, or other game state.

        Warning: scanning the full MEM1 range (~24 MB) takes several seconds.
        Use a narrower range if you have a hypothesis about where the data lives.

        Args:
            start: Start of scan range as hex (default: 0x80000000 = MEM1 start).
            end: End of scan range as hex (default: 0x81800000 = MEM1 end).
            min_abs: Minimum absolute float value to include (default: 0.1).
            max_abs: Maximum absolute float value to include (default: 50000.0).
        """
        try:
            gc_start = int(start, 16)
            gc_end = int(end, 16)
        except ValueError:
            return "Error: start and end must be hex addresses."

        if gc_end - gc_start > 0x02000000:
            return "Error: scan range too large (max 32 MB). Narrow your range."

        try:
            results = scan_floats_in_range(
                session.pid,
                gc_start,
                gc_end,
                min_abs=min_abs,
                max_abs=max_abs,
            )
        except Exception as e:
            return f"Error during scan: {e}"

        count = len(results)
        if count == 0:
            return f"No plausible floats found in 0x{gc_start:08X}–0x{gc_end:08X}."

        # Return summary + first 100 entries sorted by address
        sorted_addrs = sorted(results.keys())
        sample = sorted_addrs[:100]
        lines = [f"Found {count} plausible floats in 0x{gc_start:08X}–0x{gc_end:08X}:"]
        for addr in sample:
            lines.append(f"  0x{addr:08X} = {results[addr]:.4f}")
        if count > 100:
            lines.append(f"  ... and {count - 100} more (narrow range to see all)")
        return "\n".join(lines)

    return execute


# ── Differential scan tool ────────────────────────────────────────────── #


@tool
def scan_memory_diff(session: DolphinSession) -> Tool:
    """Build a differential memory scan tool bound to a DolphinSession."""

    # Store the last scan result for diffing
    _last_scan: dict[int, float] = {}

    async def execute(
        start: str = "0x80000000",
        end: str = "0x81800000",
        min_delta: float = 0.5,
        max_delta: float = 500.0,
    ) -> str:
        """Scan memory and compare against the previous scan to find changed values.

        Call this twice: once before sending input, once after. The second call
        shows which float addresses changed, helping identify position data.

        Only addresses present in both scans with a delta in [min_delta, max_delta]
        are returned. This filters out frame counters (huge delta) and static data
        (zero delta).

        Args:
            start: Start of scan range as hex.
            end: End of scan range as hex.
            min_delta: Minimum absolute change to report (default: 0.5).
            max_delta: Maximum absolute change to report (default: 500.0).
        """
        try:
            gc_start = int(start, 16)
            gc_end = int(end, 16)
        except ValueError:
            return "Error: start and end must be hex addresses."

        if gc_end - gc_start > 0x02000000:
            return "Error: scan range too large (max 32 MB)."

        try:
            current = scan_floats_in_range(session.pid, gc_start, gc_end)
        except Exception as e:
            return f"Error during scan: {e}"

        if not _last_scan:
            _last_scan.update(current)
            return (
                f"Baseline scan captured: {len(current)} floats in "
                f"0x{gc_start:08X}–0x{gc_end:08X}.\n"
                f"Now send input (e.g. walk_forward), then call scan_memory_diff "
                f"again to see what changed."
            )

        # Compute diffs
        changed: list[tuple[int, float, float, float]] = []
        for addr in sorted(_last_scan.keys()):
            if addr not in current:
                continue
            old_val = _last_scan[addr]
            new_val = current[addr]
            delta = abs(new_val - old_val)
            if min_delta <= delta <= max_delta:
                changed.append((addr, old_val, new_val, delta))

        # Update stored scan
        _last_scan.clear()
        _last_scan.update(current)

        if not changed:
            return (
                f"No addresses changed by [{min_delta}, {max_delta}] delta. "
                f"Try adjusting thresholds or sending different input."
            )

        # Sort by delta descending, show top 50
        changed.sort(key=lambda x: x[3], reverse=True)
        lines = [f"Found {len(changed)} addresses that changed:"]
        for addr, old_v, new_v, delta in changed[:50]:
            lines.append(f"  0x{addr:08X}: {old_v:+.4f} -> {new_v:+.4f} (delta={delta:.4f})")
        if len(changed) > 50:
            lines.append(f"  ... and {len(changed) - 50} more")
        return "\n".join(lines)

    return execute


# ── Write watchpoint tool ─────────────────────────────────────────────── #


@tool
def find_writers(session: DolphinSession) -> Tool:
    """Build a write-watchpoint tool bound to a DolphinSession."""

    async def execute(address: str, duration: float = 3.0) -> str:
        """Find all code locations that write to a GameCube memory address.

        Sets a hardware write watchpoint via the GDB stub, lets the game run
        for `duration` seconds, and collects every unique program counter (PC)
        that writes to the address. Use this to trace which function is
        responsible for updating a value (e.g. player position).

        After getting the PCs, use `decompile(pc_address)` to see the code
        that writes to this address. This is how you distinguish the
        authoritative source (e.g. player_movement_update writing object+0x24)
        from copies (camera sync, HUD cache, etc.).

        Note: the game pauses briefly during watchpoint setup and on each hit.
        Keep duration short (2-5s) to avoid excessive pauses.

        Args:
            address: Hex address to watch (e.g. "0x80B96E10").
            duration: How long to monitor in seconds (default: 3.0).
        """
        try:
            gc_addr = int(address, 16)
        except ValueError:
            return f"Error: invalid hex address '{address}'"

        if duration > 15.0:
            return "Error: duration capped at 15 seconds."

        if session._gdb is None:
            return "Error: GDB stub not available — session was not started with gdb_port."

        try:
            hits = session.find_writers(gc_addr, duration=duration)
        except Exception as e:
            return f"Error during watchpoint monitoring: {e}"

        if not hits:
            return (
                f"No writes to 0x{gc_addr:08X} observed in {duration:.1f}s. "
                f"Try sending input while monitoring (the address may only be "
                f"written during movement)."
            )

        lines = [f"Found {len(hits)} code locations writing to 0x{gc_addr:08X}:"]
        for hit in sorted(hits, key=lambda h: h.count, reverse=True):
            lines.append(f"  PC=0x{hit.pc:08X}  hits={hit.count}")
        lines.append("")
        lines.append(
            "Use decompile('0x...') on these PCs to see the writing code. "
            "The authoritative position writer is typically in the player "
            "movement/physics function, not a camera sync or HUD copy."
        )
        return "\n".join(lines)

    return execute
