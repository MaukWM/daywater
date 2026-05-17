"""Pixel-diff primitives for Dolphin frame dumps.

Pure NumPy + Pillow. No I/O beyond loading PNGs on request. The scorer
(Phase D) and the agent feedback path will both call `diff_stats` over
caller-supplied regions.

Frame index discovery uses Dolphin's master-build PNG naming convention
(`framedump_<N>.png`). For AVI dumps (older Dolphin builds, or master with
`DumpFramesAsImages = False`), extract frames via ffmpeg into a dir first
then point `load_png_frames` at that dir.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import TypedDict

import numpy as np
from numpy.typing import NDArray
from PIL import Image

FRAME_RE = re.compile(r"framedump_(\d+)\.png$")

Region = tuple[int, int, int, int]  # (x0, y0, x1, y1) in pixel coords
ImageArray = NDArray[np.uint8]


class DiffStats(TypedDict):
    mean: float
    p99: float
    max: float
    pct_pixels_changed: float


MIN_FRAME_BYTES = 10_000  # skip tiny boot/transition frames


def load_png_frames(d: Path) -> dict[int, Path]:
    """Index a directory of Dolphin PNG frame dumps by frame number.

    Skips frames smaller than MIN_FRAME_BYTES (corrupt/truncated boot frames).
    """
    out: dict[int, Path] = {}
    if not d.is_dir():
        return out
    for p in d.iterdir():
        m = FRAME_RE.search(p.name)
        if m and p.stat().st_size >= MIN_FRAME_BYTES:
            out[int(m.group(1))] = p
    return out


def load_image_rgb(p: Path) -> ImageArray:
    """Load a PNG as a `(H, W, 3) uint8` NumPy array.

    Tolerates truncated images by enabling Pillow's truncation flag.
    """
    from PIL import ImageFile

    ImageFile.LOAD_TRUNCATED_IMAGES = True
    return np.asarray(Image.open(p).convert("RGB"), dtype=np.uint8)


def diff_stats(
    a: ImageArray,
    b: ImageArray,
    region: Region | None = None,
    *,
    change_threshold: int = 5,
) -> DiffStats:
    """Per-region pixel-difference summary.

    Region is `(x0, y0, x1, y1)` in pixel coords; `None` = whole frame.
    `pct_pixels_changed` counts pixels whose summed-channel absolute diff
    exceeds `change_threshold` (defaults to a quiet-noise floor).
    """
    if region is not None:
        x0, y0, x1, y1 = region
        a = a[y0:y1, x0:x1]
        b = b[y0:y1, x0:x1]
    diff = np.abs(a.astype(np.int16) - b.astype(np.int16))
    return DiffStats(
        mean=float(diff.mean()),
        p99=float(np.percentile(diff, 99)),
        max=float(diff.max()),
        pct_pixels_changed=float((diff.sum(axis=-1) > change_threshold).mean() * 100),
    )


def fmt_stats(s: Mapping[str, float]) -> str:
    """Format one stats dict as a single-line table row."""
    return (
        f"mean={s['mean']:6.2f}  p99={s['p99']:6.2f}  max={s['max']:6.2f}  "
        f"changed%={s['pct_pixels_changed']:5.2f}"
    )


def has_render_glitch(
    img: ImageArray,
    *,
    black_threshold: int = 10,
    min_block_ratio: float = 0.05,
    min_block_rows: int = 10,
) -> bool:
    """Detect render glitches: large contiguous black rectangles.

    Scans for runs of consecutive fully-black rows (all pixels below
    ``black_threshold``). If any such block covers >= ``min_block_ratio``
    of the total frame area, returns True.

    This avoids false positives on dark game scenes — those have texture
    variation, shadows, and ambient light. A render glitch is a solid
    block of pure black from an incomplete compositor pass.

    Args:
        img: Frame as (H, W, 3) uint8 array.
        black_threshold: Per-channel ceiling to count as black.
        min_block_ratio: Fraction of total pixels the black block must
            cover to be flagged (default 15%).
        min_block_rows: Minimum consecutive black rows to count as a
            block (ignore tiny bands < this many rows).
    """
    h, w = img.shape[:2]
    total_pixels = h * w

    # For each row, check if ALL pixels are near-black
    # A pixel is near-black if max(R,G,B) < threshold
    row_max = img.max(axis=(1, 2))  # shape (H,) — brightest channel per row
    black_rows = row_max < black_threshold  # bool array, True = entirely black row

    # Find contiguous runs of black rows
    largest_block_pixels = 0
    run_start = None
    for i in range(h):
        if black_rows[i]:
            if run_start is None:
                run_start = i
        else:
            if run_start is not None:
                run_len = i - run_start
                if run_len >= min_block_rows:
                    block_pixels = run_len * w
                    largest_block_pixels = max(largest_block_pixels, block_pixels)
                run_start = None

    # Handle run that extends to bottom of frame
    if run_start is not None:
        run_len = h - run_start
        if run_len >= min_block_rows:
            block_pixels = run_len * w
            largest_block_pixels = max(largest_block_pixels, block_pixels)

    return (largest_block_pixels / total_pixels) >= min_block_ratio
