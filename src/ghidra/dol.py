"""Extract `boot.dol` from a GameCube disc image (pure Python).

The GameCube ISO format places main.dol at an offset specified in the
disc header at byte 0x420 (4 bytes big-endian, 32-bit absolute offset).
The DOL itself starts with a 0x100-byte header describing up to 7 text
and 11 data sections; total file size = max(section_offset +
section_size) across all sections.

No external tool needed.
"""

from __future__ import annotations

import struct
from pathlib import Path

_DOL_OFFSET_FIELD = 0x420
_DOL_HEADER_SIZE = 0x100
_DOL_TEXT_SECTIONS = 7
_DOL_DATA_SECTIONS = 11
_DOL_TOTAL_SECTIONS = _DOL_TEXT_SECTIONS + _DOL_DATA_SECTIONS  # 18


def _read_be_u32(buf: bytes, offset: int) -> int:
    return struct.unpack_from(">I", buf, offset)[0]


def _dol_size(header: bytes) -> int:
    """Compute total DOL file size from its 0x100 header.

    Section offsets are at [0..0x48), sizes at [0x90..0xD8) — both as
    18 big-endian u32s in matching order. File length = 0x100 + max
    section's (offset+size relative to file start) where offset>0.
    """
    if len(header) < _DOL_HEADER_SIZE:
        raise ValueError(f"DOL header truncated: {len(header)} < {_DOL_HEADER_SIZE}")

    end = 0
    for i in range(_DOL_TOTAL_SECTIONS):
        section_off = _read_be_u32(header, i * 4)
        section_sz = _read_be_u32(header, 0x90 + i * 4)
        if section_off and section_sz:
            end = max(end, section_off + section_sz)
    if end == 0:
        raise ValueError("DOL header has no non-empty sections")
    return end


def extract_dol(iso_path: Path, out_path: Path) -> int:
    """Extract `boot.dol` from a GameCube ISO. Returns DOL file size.

    Overwrites `out_path` if present. Caller owns directory creation.
    """
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with iso_path.open("rb") as iso:
        iso.seek(_DOL_OFFSET_FIELD)
        dol_offset = struct.unpack(">I", iso.read(4))[0]
        if dol_offset == 0:
            raise ValueError(f"ISO at {iso_path} has zero DOL offset (not a valid GameCube image?)")
        iso.seek(dol_offset)
        header = iso.read(_DOL_HEADER_SIZE)
        size = _dol_size(header)
        iso.seek(dol_offset)
        data = iso.read(size)
        if len(data) != size:
            raise ValueError(f"short read on DOL: wanted {size} bytes, got {len(data)}")
    out_path.write_bytes(data)
    return size
