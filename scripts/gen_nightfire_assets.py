"""One-shot generator for the nightfire_hud_off sample assets.

Produces:

- `samples/nightfire_hud_off/reference.png` — a baseline (no-cheat) frame
  pulled from a fresh Dolphin probe run against the configured ISO +
  savestate.
- `samples/nightfire_hud_off/mask.png` — a B&W mask: white pixels mark
  HUD areas the agent must remove; black pixels must be preserved.

The mask is generated procedurally from hardcoded coordinates that match
Nightfire's HUD layout at 640×528. Replace with a hand-drawn mask once
the planned web-UI editor lands.

Run once whenever the savestate / Dolphin build changes:

    SPECTRE_NIGHTFIRE_ISO=... SPECTRE_NIGHTFIRE_SAV=... \\
      uv run python scripts/gen_nightfire_assets.py
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

from src.dolphin import collect_dump, load_png_frames, read_game_id, run_dolphin
from src.dolphin.runner import write_user_dir
from src.logging import logger

SAMPLE_DIR = Path(__file__).resolve().parents[1] / "samples" / "nightfire_hud_off"


def _capture_reference(iso: Path, savestate: Path, out_png: Path) -> None:
    tmp_root = Path(tempfile.mkdtemp(prefix="spectre_genassets_"))
    try:
        user_dir = tmp_root / "user"
        write_user_dir(user_dir, read_game_id(iso), gecko_codes=[])
        result = run_dolphin(
            user_dir=user_dir,
            iso=iso,
            log_path=tmp_root / "dolphin.log",
            savestate=savestate,
            run_seconds=10,
        )
        logger.info("probe_done", rc=result.returncode, elapsed=round(result.elapsed_seconds, 1))

        dump_dir = tmp_root / "frames"
        collect_dump(user_dir, dump_dir)
        frames = load_png_frames(dump_dir)
        if not frames:
            raise RuntimeError("Dolphin run produced no PNG frames")

        last_idx = max(frames)
        shutil.copy2(frames[last_idx], out_png)
        logger.info("reference_captured", frame_idx=last_idx, path=str(out_png))
    finally:
        shutil.rmtree(tmp_root, ignore_errors=True)


def _generate_mask(reference_png: Path, out_png: Path) -> None:
    ref = Image.open(reference_png)
    w, h = ref.size
    mask = Image.new("L", (w, h), color=0)
    draw = ImageDraw.Draw(mask)

    # Compass / radar — bottom-left circle. Box generously around it.
    draw.rectangle((10, h - 110, 130, h - 10), fill=255)
    # Ammo counter — bottom-right. Generous box around the number + label.
    draw.rectangle((w - 140, h - 100, w - 10, h - 10), fill=255)

    mask.save(out_png)
    logger.info("mask_generated", dims=f"{w}x{h}", path=str(out_png))


def main() -> int:
    iso_env = "SPECTRE_NIGHTFIRE_ISO"
    sav_env = "SPECTRE_NIGHTFIRE_SAV"
    iso_path = os.environ.get(iso_env)
    sav_path = os.environ.get(sav_env)
    if not iso_path or not sav_path:
        logger.error("missing_env", needed=[iso_env, sav_env])
        return 2

    iso = Path(iso_path).expanduser().resolve()
    savestate = Path(sav_path).expanduser().resolve()
    if not iso.exists() or not savestate.exists():
        logger.error("path_missing", iso=str(iso), savestate=str(savestate))
        return 2

    SAMPLE_DIR.mkdir(parents=True, exist_ok=True)
    reference_png = SAMPLE_DIR / "reference.png"
    mask_png = SAMPLE_DIR / "mask.png"

    _capture_reference(iso, savestate, reference_png)
    _generate_mask(reference_png, mask_png)

    logger.info("assets_generated", reference=str(reference_png), mask=str(mask_png))
    return 0


if __name__ == "__main__":
    sys.exit(main())
