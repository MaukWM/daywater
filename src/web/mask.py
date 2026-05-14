"""Mask normalization: convert canvas export to scored mask."""

from __future__ import annotations

import io
from pathlib import Path

import numpy as np
from PIL import Image

from src.web.sessions import Session, SessionState

FRAME_SIZE = (640, 480)


def normalize_mask(raw_png_bytes: bytes) -> bytes:
    """Convert a canvas-exported PNG to a normalized B&W 640x480 mask.

    Handles both:
    - RGBA images (alpha channel = strokes)
    - Greyscale/RGB (bright = HUD, dark = preserve)

    Returns PNG bytes of a single-channel uint8 image:
    - 255 = HUD (white)
    - 0 = preserve (black)
    """
    img = Image.open(io.BytesIO(raw_png_bytes))

    # Canvas exports RGBA but our mask painter draws white/black on the RGB
    # channels (alpha is always 255). Convert to greyscale via luminance.
    mask = np.array(img.convert("L"))

    # Threshold: >= 128 -> HUD (255), < 128 -> preserve (0).
    binary = np.where(mask >= 128, 255, 0).astype(np.uint8)

    out = Image.fromarray(binary, mode="L").resize(FRAME_SIZE, Image.LANCZOS)

    # Re-threshold after resize (LANCZOS introduces intermediate values).
    out = Image.fromarray(np.where(np.array(out) >= 128, 255, 0).astype(np.uint8), mode="L")

    buf = io.BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()


def save_mask(session: Session, raw_png_bytes: bytes) -> dict[str, object]:
    """Normalize and persist a mask, return coverage stats."""
    mask_bytes = normalize_mask(raw_png_bytes)

    # Validate: need both HUD (white) and preserve (black) regions.
    arr = np.array(Image.open(io.BytesIO(mask_bytes)).convert("L"))
    hud_pixels = int((arr >= 200).sum())
    preserve_pixels = int((arr <= 50).sum())
    total_pixels = arr.shape[0] * arr.shape[1]
    coverage_pct = round(100 * hud_pixels / total_pixels, 1)

    if hud_pixels == 0:
        raise ValueError("Mask has no HUD pixels (white). Paint over the HUD elements you want removed.")
    if preserve_pixels == 0:
        raise ValueError(
            f"Mask is {coverage_pct}% HUD — no preserve region (black) left. "
            f"Only paint over HUD elements, leave the rest of the scene unpainted."
        )

    session.mask_path.write_bytes(mask_bytes)

    session.transition(SessionState.MASK_READY)
    return {"ok": True, "coverage_pct": coverage_pct, "hud_pixels": hud_pixels}
