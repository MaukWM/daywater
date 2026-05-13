"""CLI: pixel-diff two Dolphin frame-dump directories.

The library function `diff_stats` is region-agnostic; this CLI bakes in
the Nightfire-tuned HUD regions for ad-hoc probing. Real per-game masks
will come from a mask-image parser in a later phase.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from src.dolphin.diff import (
    DiffStats,
    Region,
    diff_stats,
    load_image_rgb,
    load_png_frames,
)
from src.logging import logger


def nightfire_regions(width: int, height: int) -> dict[str, Region | None]:
    """Hand-tuned HUD bboxes for Nightfire at 640x528 / 640x480.

    Lives here, not in the library, because real tasks ship per-game masks
    instead of hardcoded heuristics.
    """
    return {
        "full":          None,
        "compass_bl":    (10,           height - 110, 110,           height - 10),
        "ammo_br":       (width - 130,  height - 90,  width - 10,    height - 10),
        "hud_band_bot":  (0,            height - 110, width,         height),
        "center_no_hud": (width // 4,   height // 4,  3 * width // 4, 2 * height // 3),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="Pixel-diff two frame-dump directories.")
    ap.add_argument("--a", type=Path, required=True, help="dir of frames (run A)")
    ap.add_argument("--b", type=Path, required=True, help="dir of frames (run B)")
    ap.add_argument("--label", default="A vs B")
    ap.add_argument(
        "--frames",
        type=str,
        default="last",
        help="'last', 'all', or comma-separated frame indices",
    )
    args = ap.parse_args()

    a_frames = load_png_frames(args.a)
    b_frames = load_png_frames(args.b)
    common = sorted(set(a_frames) & set(b_frames))
    if not common:
        logger.error("no_overlap", a=str(args.a), b=str(args.b))
        return 1

    if args.frames == "last":
        targets = [common[-1]]
    elif args.frames == "all":
        targets = common
    else:
        wanted = {int(s) for s in args.frames.split(",")}
        targets = sorted(set(common) & wanted)
        if not targets:
            logger.error("no_overlap_with_requested", requested=sorted(wanted))
            return 1

    sample = load_image_rgb(a_frames[targets[0]])
    h, w, _ = sample.shape
    logger.info("probe", label=args.label, frames=len(targets), dims=f"{w}x{h}")

    regions = nightfire_regions(w, h)
    agg: dict[str, list[DiffStats]] = {name: [] for name in regions}
    for idx in targets:
        a_img = load_image_rgb(a_frames[idx])
        b_img = load_image_rgb(b_frames[idx])
        for name, region in regions.items():
            agg[name].append(diff_stats(a_img, b_img, region))

    print()
    print(f"  {'region':<16}  {'mean':>6}  {'p99':>6}  {'max':>6}  {'changed%':>9}")
    for name in regions:
        means = np.array([s["mean"] for s in agg[name]])
        p99s = np.array([s["p99"] for s in agg[name]])
        maxs = np.array([s["max"] for s in agg[name]])
        chgs = np.array([s["pct_pixels_changed"] for s in agg[name]])
        print(
            f"  {name:<16}  {means.mean():6.2f}  {p99s.mean():6.2f}  "
            f"{maxs.mean():6.2f}  {chgs.mean():9.2f}"
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
