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


def load_png_frames(d: Path) -> dict[int, Path]:
    """Index a directory of Dolphin PNG frame dumps by frame number."""
    out: dict[int, Path] = {}
    if not d.is_dir():
        return out
    for p in d.iterdir():
        m = FRAME_RE.search(p.name)
        if m:
            out[int(m.group(1))] = p
    return out


def load_image_rgb(p: Path) -> ImageArray:
    """Load a PNG as a `(H, W, 3) uint8` NumPy array."""
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
