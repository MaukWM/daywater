"""Mask-based scoring for HUD-removal task.

Pure NumPy. Used in two places:

- `src.agent.tools.run_gecko`: per-call feedback to the agent.
- `src.agent.task`: final `@scorer` that grades the agent's last submission.

The mask is a single-channel uint8 image:

- White (≥ 200) pixels = HUD region (must be visually altered when the
  cheat is applied — high diff vs reference is good).
- Black (≤ 50) pixels = preservation region (must remain unchanged —
  low diff vs reference is good).
- Mid-grey (anything else) = ignored.

Both means are per-channel averaged so thresholds are comparable to the
ad-hoc `diff_stats` reports in `src.dolphin.diff`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
from numpy.typing import NDArray
from PIL import Image

from src.core.dolphin.diff import ImageArray, load_image_rgb


@dataclass(frozen=True)
class MaskScore:
    """Aggregate scoring output for a single candidate frame."""

    hud_mean: float
    preserve_mean: float
    hud_pass: bool
    preserve_pass: bool
    hud_pixels: int
    preserve_pixels: int

    @property
    def passed(self) -> bool:
        return self.hud_pass and self.preserve_pass

    @property
    def verdict(self) -> str:
        return "PASS" if self.passed else "FAIL"

    def reason(self) -> str:
        if self.passed:
            return "HUD region changed enough AND preserve region stayed quiet."
        bits = []
        if not self.hud_pass:
            bits.append(f"HUD mean diff {self.hud_mean:.2f} below threshold (need bigger)")
        if not self.preserve_pass:
            bits.append(f"preserve mean diff {self.preserve_mean:.2f} above threshold (need smaller)")
        return " / ".join(bits)


def load_mask(path: Path) -> NDArray[np.uint8]:
    """Load a single-channel mask PNG."""
    return np.asarray(Image.open(path).convert("L"), dtype=np.uint8)


def score_against_mask(
    reference: ImageArray,
    candidate: ImageArray,
    mask: NDArray[np.uint8],
    *,
    hud_min_mean: float = 5.0,
    preserve_max_mean: float = 2.0,
) -> MaskScore:
    """Compute HUD vs preserve mean per-channel pixel diffs and pass/fail."""
    if reference.shape != candidate.shape:
        # Different Dolphin builds produce different resolutions; resize
        # candidate to match reference so scoring still works.
        from PIL import Image

        h, w = reference.shape[:2]
        candidate = np.asarray(
            Image.fromarray(candidate).resize((w, h), Image.LANCZOS),
            dtype=np.uint8,
        )
    if mask.shape != reference.shape[:2]:
        raise ValueError(
            f"mask shape {mask.shape} != frame shape {reference.shape[:2]}"
        )

    diff_per_channel = np.abs(reference.astype(np.int16) - candidate.astype(np.int16))
    diff_per_pixel = diff_per_channel.mean(axis=-1)  # H x W, average across RGB

    hud_pixels = mask >= 200
    preserve_pixels = mask <= 50

    if not hud_pixels.any():
        raise ValueError("mask has no HUD (white) pixels")
    if not preserve_pixels.any():
        raise ValueError("mask has no preserve (black) pixels")

    hud_mean = float(diff_per_pixel[hud_pixels].mean())
    preserve_mean = float(diff_per_pixel[preserve_pixels].mean())

    return MaskScore(
        hud_mean=hud_mean,
        preserve_mean=preserve_mean,
        hud_pass=hud_mean >= hud_min_mean,
        preserve_pass=preserve_mean <= preserve_max_mean,
        hud_pixels=int(hud_pixels.sum()),
        preserve_pixels=int(preserve_pixels.sum()),
    )


def load_and_score(
    reference_path: Path,
    candidate_path: Path,
    mask_path: Path,
    *,
    hud_min_mean: float = 5.0,
    preserve_max_mean: float = 2.0,
) -> MaskScore:
    """File-path convenience wrapper around `score_against_mask`."""
    return score_against_mask(
        reference=load_image_rgb(reference_path),
        candidate=load_image_rgb(candidate_path),
        mask=load_mask(mask_path),
        hud_min_mean=hud_min_mean,
        preserve_max_mean=preserve_max_mean,
    )
