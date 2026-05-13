"""CLI: run Dolphin once, dump frames, optionally extract last PNG.

Mirrors what `mac_harness.py` did before Phase B refactor. Lives here so
the agent's tool layer can keep calling the library directly while humans
still get a `uv run spectre-probe ...` for ad-hoc checks.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from src.dolphin import (
    collect_dump,
    extract_last_png,
    parse_gecko,
    read_game_id,
    run_dolphin,
)
from src.dolphin.runner import VideoBackend, write_user_dir
from src.logging import logger

VIDEO_BACKENDS: tuple[VideoBackend, ...] = ("Software", "OGL", "Metal", "Vulkan", "Null")


def main() -> int:
    ap = argparse.ArgumentParser(description="Run Dolphin once and dump frames.")
    ap.add_argument("--iso", required=True, type=Path)
    ap.add_argument("--savestate", type=Path, default=None)
    ap.add_argument(
        "--gecko",
        type=Path,
        default=None,
        help="Path to gecko codes text file ($Name then code lines).",
    )
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--run-seconds", type=int, default=20)
    ap.add_argument("--video-backend", default="Software", choices=VIDEO_BACKENDS)
    ap.add_argument(
        "--extract-last-png",
        action="store_true",
        help="Run ffmpeg to extract last frame of framedump as last.png.",
    )
    ap.add_argument(
        "--keep-user-dir",
        action="store_true",
        help="Don't delete temp user dir on exit (for debugging).",
    )
    ap.add_argument(
        "--show-window",
        action="store_true",
        help="Launch Dolphin visibly (default: hidden via `open -gjn`).",
    )
    args = ap.parse_args()

    iso: Path = args.iso.resolve()
    if not iso.exists():
        logger.error("iso_not_found", path=str(iso))
        return 2

    out_dir: Path = args.out.resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    game_id = read_game_id(iso)
    logger.info("probe_start", iso=str(iso), game_id=game_id, run_seconds=args.run_seconds)

    gecko_codes = []
    if args.gecko is not None:
        if not args.gecko.exists():
            logger.error("gecko_not_found", path=str(args.gecko))
            return 2
        gecko_codes = parse_gecko(args.gecko.read_text())
        logger.info("gecko_loaded", codes=[c.name for c in gecko_codes])

    savestate = args.savestate.resolve() if args.savestate else None
    if savestate is not None and not savestate.exists():
        logger.error("savestate_not_found", path=str(savestate))
        return 2

    tmp_root = Path(tempfile.mkdtemp(prefix="spectre_probe_"))
    user_dir = tmp_root / "user"
    try:
        write_user_dir(user_dir, game_id, gecko_codes)
        result = run_dolphin(
            user_dir=user_dir,
            iso=iso,
            log_path=out_dir / "dolphin.log",
            savestate=savestate,
            video_backend=args.video_backend,
            run_seconds=args.run_seconds,
            hidden=not args.show_window,
        )
        logger.info("dolphin_done", rc=result.returncode, elapsed=round(result.elapsed_seconds, 1))

        dumped = collect_dump(user_dir, out_dir / "frames")
        logger.info("dump_collected", count=len(dumped))

        if args.extract_last_png:
            avi = next((p for p in dumped if p.suffix.lower() == ".avi"), None)
            if avi is None:
                logger.info("png_extract_skipped", reason="no avi in dump")
            else:
                png = out_dir / "last.png"
                ok = extract_last_png(avi, png)
                logger.info("png_extract", ok=ok, path=str(png))

        return 0 if dumped else 1
    finally:
        if args.keep_user_dir:
            logger.info("user_dir_kept", path=str(user_dir))
        else:
            shutil.rmtree(tmp_root, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
