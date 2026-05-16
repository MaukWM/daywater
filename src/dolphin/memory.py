"""Read GameCube emulated RAM from a running Dolphin process.

Uses ``process_vm_readv`` (Linux) or ``/proc/<pid>/mem`` fallback to read
Dolphin's host memory where GameCube MEM1 (24 MB, 0x80000000–0x81800000) is
mapped.

MEM1 discovery strategy (from dolphin-memory-engine):
1. Parse ``/proc/<pid>/maps`` for regions originally backed by
   ``/dev/shm/dolphin-emu.<pid>`` (name persists even after Dolphin's
   ``shm_unlink``).
2. Fallback: look for a 24 MB anonymous ``rw-p`` mapping.
3. Validate by reading the disc header magic at GC address 0x80000000.
"""

from __future__ import annotations

import ctypes
import ctypes.util
import re
import struct
import sys
from pathlib import Path

from src.logging import logger

# GameCube MEM1 is exactly 24 MB
MEM1_SIZE = 0x0180_0000  # 24 * 1024 * 1024

# GC virtual address mask — strip the 0x80 prefix to get physical offset
GC_ADDR_MASK = 0x01FF_FFFF


class DolphinMemoryError(Exception):
    """Failed to locate or read Dolphin's emulated RAM."""


# --------------------------------------------------------------------------- #
# MEM1 base discovery                                                         #
# --------------------------------------------------------------------------- #

_MAPS_LINE_RE = re.compile(
    r"^([0-9a-f]+)-([0-9a-f]+)\s+(\S+)\s+\S+\s+\S+\s+\S+\s*(.*)"
)


def find_mem1_base(pid: int) -> int:
    """Locate the host virtual address of GameCube MEM1 in Dolphin's address space.

    Raises DolphinMemoryError if MEM1 cannot be found.
    """
    if sys.platform != "linux":
        raise DolphinMemoryError(
            f"process_vm_readv memory reading is Linux-only (got {sys.platform}). "
            f"Use MemoryWatcher (src.dolphin.watcher) on macOS."
        )

    maps_path = Path(f"/proc/{pid}/maps")
    if not maps_path.exists():
        raise DolphinMemoryError(f"/proc/{pid}/maps not found — is Dolphin running?")

    candidates: list[tuple[int, str]] = []  # (base_addr, reason)

    for line in maps_path.read_text().splitlines():
        m = _MAPS_LINE_RE.match(line)
        if not m:
            continue

        start = int(m.group(1), 16)
        end = int(m.group(2), 16)
        perms = m.group(3)
        pathname = m.group(4).strip()
        size = end - start

        # Strategy 1: region backed by dolphin-emu shm (most reliable)
        if "dolphin-emu" in pathname and size == MEM1_SIZE and "r" in perms:
            candidates.append((start, f"shm match: {pathname}"))
            continue

        # Strategy 2: anonymous rw-p region of exactly MEM1 size
        if (
            size == MEM1_SIZE
            and perms == "rw-p"
            and pathname == ""
        ):
            candidates.append((start, "anonymous 24MB rw-p"))

    if not candidates:
        raise DolphinMemoryError(
            f"Could not find MEM1 (24 MB region) in /proc/{pid}/maps. "
            f"Is Dolphin running and has it loaded a game?"
        )

    # Prefer shm-backed over anonymous
    candidates.sort(key=lambda c: (0 if "shm" in c[1] else 1))

    # Validate: read first 4 bytes — should be a valid GC disc magic
    for base, reason in candidates:
        try:
            header = _raw_read(pid, base, 6)
            # GC disc headers start with a 6-byte game ID (printable ASCII)
            if all(0x20 <= b <= 0x7E for b in header):
                logger.info(
                    "mem1_found",
                    pid=pid,
                    base=hex(base),
                    reason=reason,
                    game_id=header.decode("ascii"),
                )
                return base
        except DolphinMemoryError:
            continue

    # If no candidate validated, return the best guess anyway
    best_base, best_reason = candidates[0]
    logger.warning(
        "mem1_unvalidated",
        pid=pid,
        base=hex(best_base),
        reason=best_reason,
    )
    return best_base


# --------------------------------------------------------------------------- #
# Low-level reads                                                             #
# --------------------------------------------------------------------------- #


def _raw_read(pid: int, host_addr: int, size: int) -> bytes:
    """Read *size* bytes from *host_addr* in process *pid*.

    Tries ``process_vm_readv`` first (faster, no fd), falls back to
    ``/proc/<pid>/mem``.
    """
    try:
        return _process_vm_readv(pid, host_addr, size)
    except OSError:
        return _proc_mem_read(pid, host_addr, size)


def _process_vm_readv(pid: int, addr: int, size: int) -> bytes:
    """Use the ``process_vm_readv`` syscall for zero-copy cross-process read."""
    libc_name = ctypes.util.find_library("c")
    if libc_name is None:
        raise OSError("libc not found")
    libc = ctypes.CDLL(libc_name, use_errno=True)

    class Iovec(ctypes.Structure):
        _fields_ = [("iov_base", ctypes.c_void_p), ("iov_len", ctypes.c_size_t)]

    buf = ctypes.create_string_buffer(size)
    local = Iovec(ctypes.cast(buf, ctypes.c_void_p), size)
    remote = Iovec(ctypes.c_void_p(addr), size)

    nread = libc.process_vm_readv(
        ctypes.c_int(pid),
        ctypes.byref(local),
        ctypes.c_ulong(1),
        ctypes.byref(remote),
        ctypes.c_ulong(1),
        ctypes.c_ulong(0),
    )
    if nread < 0:
        errno = ctypes.get_errno()
        raise OSError(errno, f"process_vm_readv failed for pid={pid} addr={hex(addr)}")
    return buf.raw[:nread]


def _proc_mem_read(pid: int, addr: int, size: int) -> bytes:
    """Fallback: read via ``/proc/<pid>/mem``."""
    mem_path = Path(f"/proc/{pid}/mem")
    try:
        with mem_path.open("rb") as f:
            f.seek(addr)
            data = f.read(size)
            if len(data) < size:
                raise DolphinMemoryError(
                    f"Short read from /proc/{pid}/mem: got {len(data)}, wanted {size}"
                )
            return data
    except OSError as exc:
        raise DolphinMemoryError(
            f"Failed to read /proc/{pid}/mem at {hex(addr)}: {exc}"
        ) from exc


# --------------------------------------------------------------------------- #
# High-level GameCube address reads                                           #
# --------------------------------------------------------------------------- #

# Cache MEM1 base per pid to avoid re-scanning maps on every read
_mem1_cache: dict[int, int] = {}


def _get_mem1_base(pid: int) -> int:
    if pid not in _mem1_cache:
        _mem1_cache[pid] = find_mem1_base(pid)
    return _mem1_cache[pid]


def clear_mem1_cache(pid: int | None = None) -> None:
    """Clear the MEM1 base address cache (e.g. after Dolphin restarts)."""
    if pid is None:
        _mem1_cache.clear()
    else:
        _mem1_cache.pop(pid, None)


def read_gc_bytes(pid: int, gc_address: int, size: int) -> bytes:
    """Read *size* bytes from a GameCube virtual address (0x80XXXXXX range).

    Translates the GC address to Dolphin's host address space and reads.
    """
    mem1_base = _get_mem1_base(pid)
    offset = gc_address & GC_ADDR_MASK
    if offset + size > MEM1_SIZE:
        raise DolphinMemoryError(
            f"GC address {hex(gc_address)} + {size} bytes exceeds MEM1 bounds"
        )
    return _raw_read(pid, mem1_base + offset, size)


def read_gc_u8(pid: int, gc_address: int) -> int:
    """Read an unsigned 8-bit integer from a GameCube address."""
    return read_gc_bytes(pid, gc_address, 1)[0]


def read_gc_u16(pid: int, gc_address: int) -> int:
    """Read a big-endian unsigned 16-bit integer from a GameCube address."""
    return struct.unpack(">H", read_gc_bytes(pid, gc_address, 2))[0]


def read_gc_u32(pid: int, gc_address: int) -> int:
    """Read a big-endian unsigned 32-bit integer from a GameCube address."""
    return struct.unpack(">I", read_gc_bytes(pid, gc_address, 4))[0]


def read_gc_i32(pid: int, gc_address: int) -> int:
    """Read a big-endian signed 32-bit integer from a GameCube address."""
    return struct.unpack(">i", read_gc_bytes(pid, gc_address, 4))[0]


def read_gc_float(pid: int, gc_address: int) -> float:
    """Read a big-endian 32-bit float from a GameCube address.

    GameCube uses big-endian PowerPC — all multi-byte values are big-endian.
    """
    return struct.unpack(">f", read_gc_bytes(pid, gc_address, 4))[0]


def read_gc_floats(
    pid: int, addresses: list[int]
) -> list[float]:
    """Read multiple big-endian floats, one per GameCube address."""
    return [read_gc_float(pid, addr) for addr in addresses]


# --------------------------------------------------------------------------- #
# Bulk scanning                                                               #
# --------------------------------------------------------------------------- #


def read_gc_region(pid: int, gc_start: int, size: int) -> bytes:
    """Read a contiguous region of GameCube memory in one syscall.

    Much faster than per-address reads for scanning large ranges.
    """
    mem1_base = _get_mem1_base(pid)
    offset = gc_start & GC_ADDR_MASK
    if offset + size > MEM1_SIZE:
        # Clamp to MEM1 bounds
        size = MEM1_SIZE - offset
    return _raw_read(pid, mem1_base + offset, size)


def scan_floats_in_range(
    pid: int,
    gc_start: int,
    gc_end: int,
    *,
    min_abs: float = 0.1,
    max_abs: float = 50000.0,
) -> dict[int, float]:
    """Bulk-scan a GC address range for plausible position floats.

    Reads the entire range in chunks and extracts all 4-byte-aligned
    big-endian floats that are finite, nonzero, and within the given
    absolute value bounds.

    Returns {gc_address: float_value} for all matches.
    """
    import math

    CHUNK = 0x10000  # 64 KB per read
    results: dict[int, float] = {}

    addr = gc_start
    while addr < gc_end:
        chunk_size = min(CHUNK, gc_end - addr)
        try:
            data = read_gc_region(pid, addr, chunk_size)
        except DolphinMemoryError:
            addr += chunk_size
            continue

        # Parse all 4-byte-aligned floats from the chunk
        for i in range(0, len(data) - 3, 4):
            val = struct.unpack(">f", data[i : i + 4])[0]
            if val != 0.0 and math.isfinite(val) and min_abs < abs(val) < max_abs:
                results[addr + i] = val

        addr += chunk_size

    return results
