"""Dolphin MemoryWatcher integration — continuous monitoring of known addresses.

Dolphin's built-in MemoryWatcher (``Source/Core/Core/MemoryWatcher.cpp``)
watches a list of GameCube addresses and sends value-change notifications
over a Unix domain datagram socket.

Setup (must happen before Dolphin starts):

1. Write ``<UserDir>/MemoryWatcher/Locations.txt`` with addresses to watch.
2. Create a Unix datagram socket at ``<UserDir>/MemoryWatcher/MemoryWatcher``.
3. Boot Dolphin — it connects to the socket and sends updates every ~2 ms.

Output format: pairs of lines on the socket — address, then hex u32 value::

    80123456
    42C80000

Values are only sent when they change (delta-based). All values are raw
big-endian u32 in hex — floats must be reinterpreted from the 4-byte
representation.

Used by SmashBot, Slippi, and other competitive Melee tools.
"""

from __future__ import annotations

import math
import os
import socket
import struct
import time
from dataclasses import dataclass, field
from pathlib import Path

from src.logging import logger


@dataclass(frozen=True)
class PositionSample:
    """A single position reading at a point in time."""

    x: float
    y: float
    z: float
    timestamp: float  # monotonic seconds since listener start


# --------------------------------------------------------------------------- #
# Configuration                                                               #
# --------------------------------------------------------------------------- #


def write_locations_file(user_dir: Path, gc_addresses: list[int]) -> Path:
    """Write ``MemoryWatcher/Locations.txt`` with the addresses to monitor.

    Must be called before Dolphin starts. Addresses are GameCube virtual
    addresses (0x80XXXXXX).

    Returns the path to the written file.
    """
    mw_dir = user_dir / "MemoryWatcher"
    mw_dir.mkdir(parents=True, exist_ok=True)
    locations_path = mw_dir / "Locations.txt"

    # Format: one address per line, no 0x prefix, uppercase hex
    lines = [f"{addr:08X}" for addr in gc_addresses]
    locations_path.write_text("\n".join(lines) + "\n")

    logger.debug(
        "memory_watcher_locations",
        path=str(locations_path),
        addresses=[hex(a) for a in gc_addresses],
    )
    return locations_path


def create_watcher_socket(user_dir: Path) -> socket.socket:
    """Create the Unix datagram socket that Dolphin's MemoryWatcher connects to.

    Must be called before Dolphin starts. Returns the bound socket.
    """
    mw_dir = user_dir / "MemoryWatcher"
    mw_dir.mkdir(parents=True, exist_ok=True)
    sock_path = mw_dir / "MemoryWatcher"

    # Remove stale socket file
    if sock_path.exists():
        sock_path.unlink()

    sock = socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM)
    sock.bind(str(sock_path))
    sock.setblocking(False)

    logger.debug("memory_watcher_socket", path=str(sock_path))
    return sock


# --------------------------------------------------------------------------- #
# Listener                                                                    #
# --------------------------------------------------------------------------- #


def _hex_u32_to_float(hex_str: str) -> float:
    """Reinterpret a hex u32 string as a big-endian IEEE 754 float."""
    raw = int(hex_str, 16)
    packed = struct.pack(">I", raw)
    return struct.unpack(">f", packed)[0]


@dataclass
class MemoryWatcherListener:
    """Receives and accumulates value updates from Dolphin's MemoryWatcher.

    Typical usage::

        sock = create_watcher_socket(user_dir)
        write_locations_file(user_dir, [x_addr, y_addr, z_addr])
        # ... start Dolphin ...
        listener = MemoryWatcherListener(sock, x_addr, y_addr, z_addr)
        # ... let game run for a few seconds ...
        samples = listener.drain()
    """

    sock: socket.socket
    x_addr: int
    y_addr: int
    z_addr: int

    _current: dict[int, float] = field(default_factory=dict, init=False)
    _samples: list[PositionSample] = field(default_factory=list, init=False)
    _t0: float = field(default_factory=time.monotonic, init=False)

    def drain(self) -> list[PositionSample]:
        """Read all pending datagrams from the socket, return accumulated samples.

        Non-blocking: returns immediately if no data is available. Call
        periodically or after a delay to collect updates.
        """
        while True:
            try:
                data = self.sock.recv(4096)
            except BlockingIOError:
                break

            if not data:
                break

            self._process_datagram(data)

        return list(self._samples)

    def drain_for(self, seconds: float, poll_interval: float = 0.05) -> list[PositionSample]:
        """Drain the socket for *seconds*, polling at *poll_interval*.

        Returns all accumulated samples after the polling period.
        """
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            self.drain()
            remaining = deadline - time.monotonic()
            if remaining > 0:
                time.sleep(min(poll_interval, remaining))
        self.drain()  # final drain
        return list(self._samples)

    def get_latest_position(self) -> tuple[float, float, float] | None:
        """Return the latest known (x, y, z) or None if no data received yet."""
        x = self._current.get(self.x_addr)
        y = self._current.get(self.y_addr)
        z = self._current.get(self.z_addr)
        if x is None or y is None or z is None:
            return None
        return (x, y, z)

    def clear(self) -> None:
        """Reset accumulated samples and current values."""
        self._samples.clear()
        self._current.clear()
        self._t0 = time.monotonic()

    def close(self) -> None:
        """Close the underlying socket."""
        try:
            self.sock.close()
        except OSError:
            pass

    def _process_datagram(self, data: bytes) -> None:
        """Parse a datagram into address/value pairs and update state."""
        # Dolphin's sendto uses c_str() which NUL-terminates; strip NUL bytes
        text = data.replace(b"\x00", b"").decode("ascii", errors="replace").strip()
        if not text:
            return  # empty datagram (heartbeat when no values changed)
        lines = text.split("\n")

        # MemoryWatcher sends pairs: address line then value line
        i = 0
        while i + 1 < len(lines):
            addr_str = lines[i].strip()
            val_str = lines[i + 1].strip()
            i += 2

            if not addr_str or not val_str:
                continue

            try:
                # Address may contain spaces (pointer chain), use first token
                # for matching against our configured addresses
                gc_addr = int(addr_str.split()[0], 16)
                value = _hex_u32_to_float(val_str)
            except (ValueError, struct.error):
                continue

            # Skip NaN/Inf values (likely uninitialised memory)
            if math.isnan(value) or math.isinf(value):
                continue

            self._current[gc_addr] = value

            # Record a position sample whenever any tracked axis updates
            if gc_addr in (self.x_addr, self.y_addr, self.z_addr):
                pos = self.get_latest_position()
                if pos is not None:
                    self._samples.append(
                        PositionSample(
                            x=pos[0],
                            y=pos[1],
                            z=pos[2],
                            timestamp=time.monotonic() - self._t0,
                        )
                    )
